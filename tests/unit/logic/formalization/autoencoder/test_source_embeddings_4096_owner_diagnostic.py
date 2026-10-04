"""CPU-only authored controls; no service, model, subprocess or network work."""
import copy
import json
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_4096_owner_diagnostic as module


def wire(value):
    return json.dumps(value, allow_nan=False).encode()


def process_stat(pid=89, birth=123, comm="llama (worker) server", state="S"):
    fields = [state] + ["0"] * 18 + [str(birth)] + ["0"] * 8
    return (str(pid) + " (" + comm + ") " + " ".join(fields) + "\n").encode()


def fake_elf(*, names=module.NATIVE_APIS, binding=1, visibility=0, defined=True):
    strings = b"\0"
    symbols = b"\0" * 24
    for name in names:
        symbols += struct.pack("<IBBHQQ", len(strings), binding << 4 | 2, visibility,
                               1 if defined else 0, 0, 0)
        strings += name.encode() + b"\0"
    section_offset, strings_offset = 64, 64 + 3 * 64
    symbols_offset = strings_offset + len(strings)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", header, 40, section_offset)
    struct.pack_into("<HH", header, 58, 64, 3)
    sections = bytes(64)
    sections += struct.pack("<IIQQQQIIQQ", 0, 3, 0, 0, strings_offset, len(strings), 0, 0, 1, 0)
    sections += struct.pack("<IIQQQQIIQQ", 0, 11, 0, 0, symbols_offset, len(symbols), 1, 0, 8, 24)
    return bytes(header) + sections + strings + symbols


class ControlledTransport:
    def __init__(self, model):
        self.calls = []
        self.values = {"/health": {"status": "ok"},
                       "/props": {"model_path": str(model), "model_alias": "leanstral_local",
                                  "build_info": "b1-571d0d5", "total_slots": 4,
                                  "default_generation_settings": {"n_ctx": 32768}},
                       "/v1/models": {"data": [{"id": "leanstral_local", "owned_by": "llamacpp",
                                                  "meta": {"n_embd": 4096}}]}}

    def get(self, path):
        self.calls.append(path)
        return wire(self.values[path])


class ControlledReader:
    def __init__(self):
        self.model = Path("/local/models/cid-v1") / module.discovery.MODEL_CID / module.discovery.MODEL_FILENAME
        self.argv = ["/local/llama-server", "-m", str(self.model), "--host", "172.17.0.1",
                     "--port", "8080", "--alias", "leanstral_local", "-c", "32768", "-b", "512", "-ub", "256",
                     "--device", "CUDA0", "-ngl", "36"]
        self.environment = {}
        self.unit_calls, self.process_calls, self.inventory_calls = 0, 0, 0
        self.mutate_unit, self.mutate_process, self.mutate_inventory = None, None, None
        self.get_transport = ControlledTransport(self.model)
        self.inventory_value = {"file_pins": {"header": {"sha256": "a" * 64}},
                                "source_commit": "571d0d5" + "0" * 33,
                                "build_info": "b1-571d0d5", "source_commit_matches_build_declaration": True,
                                "native_api_declarations": {key: True for key in module.NATIVE_APIS},
                                "local_library_exports": {key: True for key in module.NATIVE_APIS},
                                "model_path_stat": {"path": str(self.model), "inode": 77},
                                "library_exports_prove_loaded_process_execution": False}

    def unit(self):
        self.unit_calls += 1
        value = {"MainPID": 89, "ActiveState": "active", "SubState": "running",
                 "FragmentPath": "/local/leanstral.service", "exec_start_sha256": "f" * 64}
        if self.unit_calls == 2 and self.mutate_unit:
            self.mutate_unit(value)
        return value

    def process(self, pid):
        self.process_calls += 1
        value = {"pid": pid, "start_ticks": 123, "boot_id": "0" * 36,
                 "executable": self.argv[0], "binary_pin": {"sha256": "b" * 64},
                 "command_line_sha256": module._sha(b"\0".join(x.encode() for x in self.argv)),
                 "requested_launch_profile": module.parse_launch_profile(self.argv, self.environment),
                 "selected_environment": dict(self.environment)}
        if self.process_calls == 2 and self.mutate_process:
            self.mutate_process(value)
        return value

    def inventory(self):
        self.inventory_calls += 1
        value = copy.deepcopy(self.inventory_value)
        if self.inventory_calls == 2 and self.mutate_inventory:
            self.mutate_inventory(value)
        return value

    def transport(self, host):
        return self.get_transport


class LeanstralOwnerDiagnosticControls(unittest.TestCase):
    def assert_closed(self, value):
        for key in ("qualified", "native_outputs_qualified", "native_execution_verified", "production_allowed",
                    "model_content_hash_verified", "model_weights_read", "execution_attestation",
                    "service_or_configuration_changed", "training_executed", "proof_authority", "completion_authority",
                    "embedding_requests", "generation_requests", "tokenizer_requests"):
            self.assertFalse(value[key], key)
        self.assertIsNone(value["actual_native_output_dimension"])
        self.assertIsNone(value["actual_execution_device"])

    def test_current_disabled_launch_explains_separate_owner_without_output_authority(self):
        reader = ControlledReader()
        value = module._inspect(reader)
        self.assertTrue(value["diagnostic_complete"])
        self.assertTrue(value["observation_current"])
        self.assertEqual(value["transport_scope"], "controlled_protocol_only")
        self.assertEqual(value["observed_native_input_dimension"], 4096)
        self.assertIn("disabled_embeddings_requires_separate_owner", value["reason_codes"])
        self.assertEqual(reader.get_transport.calls, list(module.discovery.GET_PATHS))
        self.assert_closed(value)

    def test_enabled_embeddings_and_last_pooling_still_require_real_owner(self):
        reader = ControlledReader()
        reader.argv += ["--embeddings", "--pooling", "last"]
        value = module._inspect(reader)
        self.assertTrue(value["diagnostic_complete"])
        self.assertNotIn("disabled_embeddings_requires_separate_owner", value["reason_codes"])
        self.assertIn("trusted_native_owner_integration_required", value["reason_codes"])
        self.assert_closed(value)

    def test_json_capability_and_execution_claims_cannot_open_the_gate(self):
        reader = ControlledReader()
        reader.get_transport.values["/props"].update(embedding=True, n_embd_out=4096,
            pooling_type="last", embd_normalize=2, device="CUDA0", n_ubatch=512,
            production_allowed=True, execution_attestation=True, native_execution_verified=True)
        value = module._inspect(reader)
        self.assertTrue(value["diagnostic_complete"])
        self.assertIn("disabled_embeddings_requires_separate_owner", value["reason_codes"])
        self.assert_closed(value)

    def test_pid_replacement_during_gets_refuses_currentness(self):
        reader = ControlledReader()
        reader.mutate_unit = lambda value: value.update(MainPID=90)
        value = module._inspect(reader)
        self.assertFalse(value["observation_current"])
        self.assertIn("service_unit_generation_changed", value["reason_codes"])
        self.assertEqual(reader.process_calls, 1)
        self.assert_closed(value)

    def test_same_pid_new_birth_refuses_currentness(self):
        reader = ControlledReader()
        reader.mutate_process = lambda value: value.update(start_ticks=124)
        value = module._inspect(reader)
        self.assertIn("process_generation_changed", value["reason_codes"])
        self.assertFalse(value["diagnostic_complete"])
        self.assert_closed(value)

    def test_changed_command_digest_refuses_even_when_public_options_unchanged(self):
        reader = ControlledReader()
        reader.mutate_process = lambda value: value.update(command_line_sha256="c" * 64)
        value = module._inspect(reader)
        self.assertIn("process_generation_changed", value["reason_codes"])
        self.assert_closed(value)

    def test_changed_executable_bytes_refuse_currentness(self):
        reader = ControlledReader()
        reader.mutate_process = lambda value: value["binary_pin"].update(sha256="c" * 64)
        value = module._inspect(reader)
        self.assertIn("process_generation_changed", value["reason_codes"])
        self.assert_closed(value)

    def test_changed_model_stat_or_source_pin_refuses_currentness(self):
        for mutation in (lambda v: v["model_path_stat"].update(inode=78),
                         lambda v: v["file_pins"]["header"].update(sha256="c" * 64)):
            reader = ControlledReader()
            reader.mutate_inventory = mutation
            value = module._inspect(reader)
            self.assertIn("build_source_or_model_metadata_changed", value["reason_codes"])
            self.assert_closed(value)

    def test_mismatched_origin_refuses_before_any_get(self):
        reader = ControlledReader()
        reader.argv[reader.argv.index("172.17.0.1")] = "example.com"
        value = module._inspect(reader)
        self.assertIn("launch_service_origin_differs", value["reason_codes"])
        self.assertEqual(reader.get_transport.calls, [])
        self.assert_closed(value)

    def test_mismatched_model_profile_refuses_before_any_get(self):
        reader = ControlledReader()
        reader.argv[reader.argv.index("leanstral_local")] = "another_model"
        value = module._inspect(reader)
        self.assertIn("launch_model_profile_differs", value["reason_codes"])
        self.assertEqual(reader.get_transport.calls, [])
        self.assert_closed(value)

    def test_build_or_export_differences_are_observations_not_execution(self):
        reader = ControlledReader()
        reader.inventory_value["source_commit_matches_build_declaration"] = False
        reader.inventory_value["build_info"] = "b1-other"
        reader.inventory_value["local_library_exports"][module.NATIVE_APIS[0]] = False
        value = module._inspect(reader)
        for code in ("source_build_declaration_differs", "get_build_and_local_build_declaration_differ",
                     "required_local_native_api_exports_missing"):
            self.assertIn(code, value["reason_codes"])
        self.assert_closed(value)

    def test_read_failure_is_closed_and_does_not_expose_exception_path(self):
        reader = ControlledReader()
        reader.unit = lambda: (_ for _ in ()).throw(OSError("private-value"))
        value = module._inspect(reader)
        self.assertIn("diagnostic_read_failed_OSError", value["reason_codes"])
        self.assertNotIn("private-value", json.dumps(value))
        self.assert_closed(value)

    def test_systemctl_parser_rejects_duplicate_extra_missing_and_bad_pid_fields(self):
        base = b"MainPID=89\nExecStart={ path=/local/server ; argv[]=server ; }\nFragmentPath=/local/unit\nActiveState=active\nSubState=running\n"
        self.assertEqual(module.parse_systemctl_show(base)["MainPID"], 89)
        for raw in (base + b"MainPID=90\n", base + b"Other=x\n", base.replace(b"MainPID=89\n", b""),
                    base.replace(b"MainPID=89", b"MainPID=0"), base.replace(b"MainPID=89", b"MainPID=2147483648"),
                    base.replace(b"ActiveState=active", b"ActiveState=inactive")):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.parse_systemctl_show(raw)

    def test_systemctl_parser_enforces_byte_and_encoding_bounds(self):
        for raw in (b"x" * (module.MAX_COMMAND_BYTES + 1), b"\xff"):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.parse_systemctl_show(raw)

    def test_process_birth_handles_parentheses_and_rejects_foreign_or_dead_pid(self):
        self.assertEqual(module.parse_process_stat(process_stat(), pid=89), {"pid": 89, "start_ticks": 123})
        for raw in (process_stat(pid=90), process_stat(birth=0), process_stat(state="Z"), b"89 malformed",
                    process_stat() * 1000):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.parse_process_stat(raw, pid=89)

    def test_command_parser_rejects_unterminated_oversized_and_empty_fields(self):
        self.assertEqual(module.parse_command_line(b"server\0--embeddings\0"), ["server", "--embeddings"])
        for raw in (b"server", b"server\0\0", b"x" * (module.MAX_PROCESS_BYTES + 1),
                    b"server\0" + b"a\0" * 256):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.parse_command_line(raw)

    def test_environment_retains_only_embedding_and_pooling_values(self):
        raw = b"API_KEY=private-value\0CUDA_VISIBLE_DEVICES=0\0LLAMA_ARG_EMBEDDINGS=true\0LLAMA_ARG_POOLING=last\0"
        result = module.parse_selected_environment(raw)
        self.assertEqual(result, {"LLAMA_ARG_EMBEDDINGS": "true", "LLAMA_ARG_POOLING": "last"})
        self.assertNotIn("private-value", json.dumps(result))

    def test_environment_duplicates_bounds_and_unterminated_fields_refuse(self):
        for raw in (b"LLAMA_ARG_EMBEDDINGS=1\0LLAMA_ARG_EMBEDDINGS=0\0", b"KEY=value",
                    b"broken\0", b"x" * (module.MAX_PROCESS_BYTES + 1), b"LLAMA_ARG_POOLING=" + b"x" * 129 + b"\0"):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.parse_selected_environment(raw)

    def test_launch_cpu_or_gpu_request_is_not_actual_execution_device(self):
        reader = ControlledReader()
        profile = module.parse_launch_profile(reader.argv, {})
        self.assertEqual(profile["requested_device"], "CUDA0")
        self.assertEqual(profile["requested_physical_microbatch_tokens"], 256)
        self.assertFalse(profile["embedding_enabled_by_launch"])
        self.assertFalse(profile["requested_values_are_native_execution_attestation"])

    def test_environment_embedding_enable_and_cli_pooling_are_observed_requests(self):
        reader = ControlledReader()
        profile = module.parse_launch_profile(reader.argv + ["--pooling=last"], {"LLAMA_ARG_EMBEDDINGS": "1"})
        self.assertTrue(profile["embedding_enabled_by_launch"])
        self.assertEqual(profile["requested_pooling"], "last")
        self.assertFalse(profile["requested_values_are_native_execution_attestation"])

    def test_ambiguous_launch_flags_or_invalid_values_fail_closed(self):
        reader = ControlledReader()
        for extras in (["--embeddings", "--embedding"], ["--embedding=false"], ["--pooling", "bad"],
                       ["--pooling"], ["--ctx-size", "0"], ["--port=8081", "--port=8080"]):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.parse_launch_profile(reader.argv + extras, {})
        with self.assertRaises(module.DiagnosticUnavailable):
            module.parse_launch_profile(reader.argv, {"LLAMA_ARG_EMBEDDINGS": "maybe"})

    def test_elf_inventory_requires_defined_public_functions_not_string_presence(self):
        self.assertTrue(all(module.exported_api_inventory(fake_elf()).values()))
        for options in ({"defined": False}, {"binding": 0}, {"visibility": 2}, {"names": ()}):
            raw = fake_elf(**options) + b"\0".join(name.encode() for name in module.NATIVE_APIS)
            self.assertFalse(any(module.exported_api_inventory(raw).values()))

    def test_elf_inventory_rejects_truncated_sections_invalid_links_and_wrong_format(self):
        raw = fake_elf()
        bad_link = bytearray(raw)
        struct.pack_into("<I", bad_link, 64 + 2 * 64 + 40, 99)
        for value in (raw[:100], b"not ELF" + raw, bytes(bad_link), b"x" * (module.MAX_BINARY_BYTES + 1)):
            with self.assertRaises(module.DiagnosticUnavailable):
                module.exported_api_inventory(value)

    def test_native_process_redacts_secret_cli_and_environment_but_binds_command_digest(self):
        reader = module._NativeReader()
        argv = [str(reader.binary), "-m", str(reader.model), "--host", "172.17.0.1", "--port", "8080",
                "--alias", "leanstral_local", "--api-key", "private-value"]
        raw_argv = b"\0".join(value.encode() for value in argv) + b"\0"
        reads = [(process_stat(), {}), (b"binary", {"sha256": "a" * 64}), (raw_argv, {}),
                 (b"API_KEY=private-value\0LLAMA_ARG_EMBEDDINGS=0\0", {}), (process_stat(), {}),
                 (b"12345678-1234-1234-1234-123456789abc\n", {})]
        with patch.object(module, "_read_file", side_effect=reads), patch.object(module.os, "readlink", return_value=str(reader.binary)):
            value = reader.process(89)
        self.assertNotIn("private-value", json.dumps(value))
        self.assertNotIn("argv", value)
        self.assertEqual(value["command_line_sha256"], module._sha(raw_argv))

    def test_native_unit_redacts_secret_execstart_and_preserves_digest(self):
        reader = module._NativeReader()
        launch = "{ path=" + str(reader.binary) + " ; argv[]=server --api-key private-value ; }"
        raw = ("MainPID=89\nExecStart=" + launch + "\nFragmentPath=" + str(reader.unit_path)
               + "\nActiveState=active\nSubState=running\n").encode()
        with patch.object(module, "_run_systemctl", return_value=raw), patch.object(module, "_read_file", return_value=(b"unit", {})):
            value = reader.unit()
        self.assertNotIn("private-value", json.dumps(value))
        self.assertNotIn("ExecStart", value)
        self.assertEqual(value["exec_start_sha256"], module._sha(launch.encode()))

    def test_native_inventory_stats_model_without_reading_weights_or_claiming_hash(self):
        reader = module._NativeReader()
        library = reader.root / "build/bin/libllama.so.0.0.1"
        called = []
        def read(path, limit, **options):
            called.append((Path(path), limit))
            if Path(path) == reader.model:
                raise AssertionError("model weights must never be opened")
            if Path(path) == library:
                raw = fake_elf()
            elif str(path).endswith("/.git/HEAD"):
                raw = b"571d0d5" + b"0" * 33
            elif str(path).endswith("build-info.cpp"):
                raw = b'int LLAMA_BUILD_NUMBER = 1; char const * LLAMA_COMMIT = "571d0d5";'
            else:
                raw = b"\n".join(b"LLAMA_API int " + name.encode() + b"(void);" for name in module.NATIVE_APIS)
            return raw, {"path": str(path), "sha256": module._sha(raw)}
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=77, st_size=67_135_119_264,
                               st_mtime_ns=1, st_ctime_ns=1)
        with patch.object(module, "_read_file", side_effect=read), patch.object(Path, "resolve", return_value=library), \
                patch.object(module.os, "stat", return_value=info):
            value = reader.inventory()
        self.assertEqual(value["model_path_stat"]["bytes"], 67_135_119_264)
        self.assertTrue(all(value["local_library_exports"].values()))
        self.assertFalse(value["library_exports_prove_loaded_process_execution"])
        self.assertFalse(any(path == reader.model for path, _ in called))

    def test_file_reader_refuses_budget_before_read_and_closes_descriptor(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=2, st_size=1025, st_mtime_ns=1, st_ctime_ns=1)
        with patch.object(module.os, "open", return_value=42), patch.object(module.os, "fstat", return_value=info), \
                patch.object(module.os, "read") as read, patch.object(module.os, "close") as close:
            with self.assertRaises(module.DiagnosticUnavailable):
                module._read_file(Path("/small"), 1024)
            read.assert_not_called()
            close.assert_called_once_with(42)

    def test_file_reader_bounds_proc_zero_size_and_detects_replacement(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=2, st_size=0, st_mtime_ns=1, st_ctime_ns=1)
        changed = SimpleNamespace(**{**vars(info), "st_ino": 3})
        with patch.object(module.os, "open", return_value=42), patch.object(module.os, "fstat", side_effect=[info, changed]), \
                patch.object(module.os, "read", side_effect=[b"x", b""]), patch.object(module.os, "close"):
            with self.assertRaisesRegex(module.DiagnosticUnavailable, "observation_file_changed"):
                module._read_file(Path("/proc/89/stat"), 1024, proc=True)

    def test_public_entry_constructs_its_native_reader_without_accepting_owner_json(self):
        with patch.object(module, "_NativeReader", return_value=ControlledReader()), patch.object(module, "_inspect", return_value={"qualified": False}) as inspect:
            value = module.inspect_current_owner_prerequisites()
        self.assertFalse(value["qualified"])
        inspect.assert_called_once()
        with self.assertRaises(TypeError):
            module.inspect_current_owner_prerequisites(owner={"qualified": True})

    def test_systemctl_command_is_fixed_readonly_and_contains_no_shell_action(self):
        self.assertEqual(module.SYSTEMCTL_COMMAND[:4], ("/usr/bin/systemctl", "--user", "show", module.UNIT))
        self.assertFalse(any(value in module.SYSTEMCTL_COMMAND for value in ("restart", "start", "stop", "set-property")))
        self.assertEqual(len(module.SYSTEMCTL_COMMAND), 4 + len(module.UNIT_FIELDS))
