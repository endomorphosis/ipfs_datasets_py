"""Bounded observations of the existing Leanstral service's owner prerequisites.

This reads a fixed systemd unit, its current process, small native build/source
files and GET metadata. It never sends inference, opens model weights, starts
or changes a service, or accepts an owner witness. A stable observation is not
execution attestation and cannot open the separate native4096 production gate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import struct
import subprocess
import time

from . import source_embeddings_4096 as discovery

SCHEMA = "leanstral-source4096-owner-prerequisite-diagnostic/v1"
UNIT = "ipfs-accelerate-leanstral.service"
UNIT_FIELDS = ("MainPID", "ExecStart", "FragmentPath", "ActiveState", "SubState")
SYSTEMCTL_COMMAND = ("/usr/bin/systemctl", "--user", "show", UNIT,
                     *("--property=" + field for field in UNIT_FIELDS))
MAX_PROCESS_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 512 * 1024
MAX_BINARY_BYTES = 16 * 1024 * 1024
MAX_COMMAND_BYTES = 64 * 1024
MAX_COMMAND_SECONDS = 5.0
SELECTED_ENVIRONMENT = frozenset({"LLAMA_ARG_EMBEDDINGS", "LLAMA_ARG_POOLING"})
NATIVE_APIS = ("llama_model_n_embd_inp", "llama_model_n_embd_out", "llama_pooling_type",
               "llama_n_ctx", "llama_n_ubatch", "llama_tokenize",
               "llama_get_embeddings_seq", "llama_synchronize", "llama_set_abort_callback")


class DiagnosticUnavailable(ValueError):
    """A bounded/current observation could not be completed."""


def _require(condition, code):
    if not condition:
        raise DiagnosticUnavailable(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _decode(raw, limit, code):
    _require(type(raw) is bytes and len(raw) <= limit, code + "_byte_bound")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagnosticUnavailable(code + "_encoding") from exc


def _positive_integer(value, maximum, code):
    _require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,15}", value), code)
    number = int(value)
    _require(number <= maximum, code)
    return number


def parse_systemctl_show(raw):
    """Parse only the fixed requested unit fields; reject duplicates and extras."""
    value = {}
    for line in _decode(raw, MAX_COMMAND_BYTES, "unit_show").splitlines():
        _require("=" in line, "unit_show_field")
        key, field = line.split("=", 1)
        _require(key in UNIT_FIELDS and key not in value, "unit_show_field")
        value[key] = field
    _require(set(value) == set(UNIT_FIELDS), "unit_show_fields_missing")
    value["MainPID"] = _positive_integer(value["MainPID"], 2**31 - 1, "unit_main_pid")
    _require(value["ActiveState"] == "active" and value["SubState"] == "running",
             "unit_not_running")
    _require(bool(value["ExecStart"]) and bool(value["FragmentPath"]), "unit_launch_missing")
    return value


def parse_process_stat(raw, *, pid):
    """Get PID/start ticks despite spaces or parentheses in Linux's comm field."""
    text = _decode(raw, 16 * 1024, "process_stat").strip()
    _require(type(pid) is int and 1 <= pid < 2**31, "process_pid")
    prefix = str(pid) + " ("
    close = text.rfind(") ")
    _require(text.startswith(prefix) and close >= len(prefix), "process_stat_identity")
    fields = text[close + 2:].split()
    _require(len(fields) >= 20 and fields[0] not in {"Z", "X", "x"}, "process_not_live")
    ticks = _positive_integer(fields[19], 2**64 - 1, "process_birth_ticks")
    return {"pid": pid, "start_ticks": ticks}


def parse_command_line(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PROCESS_BYTES and raw.endswith(b"\0"),
             "process_argv_byte_bound_or_termination")
    fields = raw[:-1].split(b"\0")
    _require(1 <= len(fields) <= 256 and all(fields), "process_argv_fields")
    return [_decode(field, MAX_PROCESS_BYTES, "process_argv") for field in fields]


def parse_selected_environment(raw):
    """Retain only four relevant values; never return other process environment."""
    _require(type(raw) is bytes and len(raw) <= MAX_PROCESS_BYTES
             and (not raw or raw.endswith(b"\0")), "process_environment_byte_bound_or_termination")
    fields = raw[:-1].split(b"\0") if raw else []
    _require(len(fields) <= 4096, "process_environment_field_bound")
    result = {}
    for field in fields:
        _require(b"=" in field, "process_environment_field")
        key, value = field.split(b"=", 1)
        if key in {name.encode("ascii") for name in SELECTED_ENVIRONMENT}:
            name = key.decode("ascii")
            _require(name not in result, "process_environment_duplicate")
            result[name] = _decode(value, 128, "selected_environment")
    return result


def _flag_values(argv):
    aliases = {"-m": "model", "--model": "model", "--host": "host", "--port": "port",
               "--alias": "alias", "--pooling": "pooling", "-c": "context", "--ctx-size": "context",
               "-b": "batch", "--batch-size": "batch", "-ub": "microbatch", "--ubatch-size": "microbatch",
               "-ngl": "gpu_layers", "--gpu-layers": "gpu_layers", "--n-gpu-layers": "gpu_layers",
               "--device": "device", "--embd-normalize": "normalization"}
    result = {}
    embedding = False
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in {"--embedding", "--embeddings", "--rerank", "--reranking"}:
            _require(not embedding, "ambiguous_embedding_flags")
            embedding = True
        elif arg.startswith(("--embedding=", "--embeddings=", "--no-embedding")):
            raise DiagnosticUnavailable("unsupported_embedding_flag")
        else:
            key, equals, inline = arg.partition("=")
            if key in aliases:
                field = aliases[key]
                _require(field not in result, "duplicate_launch_profile_flag")
                if equals:
                    value = inline
                else:
                    index += 1
                    _require(index < len(argv), "launch_profile_flag_value_missing")
                    value = argv[index]
                _require(bool(value), "launch_profile_flag_value_missing")
                result[field] = value
        index += 1
    result["embedding_flag"] = embedding
    return result


def parse_launch_profile(argv, environment):
    _require(type(argv) is list and 1 <= len(argv) <= 256
             and all(type(value) is str and value for value in argv), "launch_argv")
    _require(type(environment) is dict and set(environment) <= SELECTED_ENVIRONMENT
             and all(type(value) is str for value in environment.values()), "launch_environment")
    values = _flag_values(argv)
    env_embedding = environment.get("LLAMA_ARG_EMBEDDINGS", "false").lower()
    _require(env_embedding in {"0", "1", "false", "true", "no", "yes", "off", "on"},
             "embedding_environment_invalid")
    enabled = values["embedding_flag"] or env_embedding in {"1", "true", "yes", "on"}
    pooling = values.get("pooling", environment.get("LLAMA_ARG_POOLING"))
    _require(pooling is None or pooling in {"none", "mean", "cls", "last", "rank"}, "pooling_profile_invalid")
    norm = values.get("normalization")
    if norm is not None:
        _require(re.fullmatch(r"-?[0-9]{1,2}", norm), "normalization_profile_invalid")
        norm = int(norm)
        _require(-1 <= norm <= 32, "normalization_profile_invalid")
    numeric = {}
    for field in ("context", "batch", "microbatch", "port"):
        numeric[field] = (_positive_integer(values[field], 2**24, "launch_" + field)
                          if field in values else None)
    return {"embedding_enabled_by_launch": enabled, "requested_pooling": pooling,
            "requested_normalization": norm, "requested_context_tokens": numeric["context"],
            "requested_logical_batch_tokens": numeric["batch"],
            "requested_physical_microbatch_tokens": numeric["microbatch"],
            "requested_device": values.get("device"), "requested_gpu_layers": values.get("gpu_layers"),
            "model_path": values.get("model"), "model_alias": values.get("alias"),
            "host": values.get("host"), "port": numeric["port"],
            "requested_values_are_native_execution_attestation": False}


def exported_api_inventory(raw):
    """Read defined public function names from bounded ELF64 LE DYNSYM bytes."""
    _require(type(raw) is bytes and 64 <= len(raw) <= MAX_BINARY_BYTES, "native_elf_byte_bound")
    _require(raw[:6] == b"\x7fELF\x02\x01", "native_elf_format")
    offset = struct.unpack_from("<Q", raw, 40)[0]
    width, count = struct.unpack_from("<HH", raw, 58)
    _require(width == 64 and 1 <= count <= 1024 and offset + width * count <= len(raw), "native_elf_sections")
    sections = [struct.unpack_from("<IIQQQQIIQQ", raw, offset + index * width) for index in range(count)]
    result = {name: False for name in NATIVE_APIS}
    found = False
    for section in sections:
        if section[1] != 11:
            continue
        found = True
        begin, size, link, entry_width = section[4], section[5], section[6], section[9]
        _require(entry_width == 24 and size % 24 == 0 and size // 24 <= 100_000
                 and begin + size <= len(raw) and link < count, "native_elf_symbols")
        strings = sections[link]
        str_begin, str_size = strings[4], strings[5]
        _require(strings[1] == 3 and str_begin + str_size <= len(raw), "native_elf_strings")
        for pos in range(begin, begin + size, 24):
            name_offset, info, other, section_index = struct.unpack_from("<IBBH", raw, pos)
            if section_index == 0 or info >> 4 not in {1, 2} or info & 15 not in {2, 10} or other & 3 not in {0, 3}:
                continue
            _require(name_offset < str_size, "native_elf_symbol_name")
            name_begin = str_begin + name_offset
            for wanted in NATIVE_APIS:
                encoded = wanted.encode("ascii") + b"\0"
                if name_begin + len(encoded) <= str_begin + str_size and raw[name_begin:name_begin + len(encoded)] == encoded:
                    result[wanted] = True
    _require(found, "native_elf_dynamic_symbols_absent")
    return result


def _identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _read_file(path, limit, *, proc=False):
    flags = os.O_RDONLY | os.O_CLOEXEC | (0 if proc else os.O_NOFOLLOW)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "observation_file_type")
        _require(before.st_size <= limit, "observation_file_byte_bound")
        pieces, total = [], 0
        while True:
            piece = os.read(descriptor, min(64 * 1024, limit + 1 - total))
            if not piece:
                break
            pieces.append(piece)
            total += len(piece)
            _require(total <= limit, "observation_file_byte_bound")
        _require(_identity(before) == _identity(os.fstat(descriptor)), "observation_file_changed")
        raw = b"".join(pieces)
        return raw, {"path": str(path), **_identity(before), "read_bytes": len(raw), "sha256": _sha(raw)}
    finally:
        os.close(descriptor)


def _run_systemctl():
    """Fixed argv, bounded output/deadline; only this read subprocess is killed."""
    process = subprocess.Popen(SYSTEMCTL_COMMAND, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                               env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
                                    **{key: os.environ[key] for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
                                       if key in os.environ}})
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + MAX_COMMAND_SECONDS
    selector = selectors.DefaultSelector()
    try:
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "unit_command_deadline")
            for key, _ in selector.select(min(remaining, 0.1)):
                block = os.read(key.fileobj.fileno(), 8192)
                if block:
                    output[key.data].extend(block)
                    _require(sum(len(value) for value in output.values()) <= MAX_COMMAND_BYTES,
                             "unit_command_output_bound")
                else:
                    selector.unregister(key.fileobj)
        _require(process.wait(timeout=max(0.001, deadline - time.monotonic())) == 0, "unit_command_failed")
        return bytes(output["stdout"])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        selector.close()
        process.stdout.close()
        process.stderr.close()


class _NativeReader:
    def __init__(self):
        self.home = Path.home()
        self.root = self.home / ".cache/ipfs_accelerate_py/llama_cpp"
        self.unit_path = self.home / ".config/systemd/user" / UNIT
        self.binary = self.root / "build/bin/llama-server"
        self.model = self.root / "models/cid-v1" / discovery.MODEL_CID / discovery.MODEL_FILENAME

    def unit(self):
        value = parse_systemctl_show(_run_systemctl())
        _require(value["FragmentPath"] == str(self.unit_path), "unit_fragment_path_differs")
        _require(value["ExecStart"].startswith("{ path=" + str(self.binary) + " ; argv[]="),
                 "unit_executable_path_differs")
        raw, pin = _read_file(self.unit_path, MAX_PROCESS_BYTES)
        # ExecStart may contain API keys. Keep only its digest for currentness.
        value["exec_start_sha256"] = _sha(value.pop("ExecStart").encode("utf-8"))
        value["fragment_pin"] = pin
        return value

    def process(self, pid):
        root = Path("/proc") / str(pid)
        stat_before, _ = _read_file(root / "stat", 16 * 1024, proc=True)
        birth = parse_process_stat(stat_before, pid=pid)
        executable = os.readlink(root / "exe")
        _require(executable == str(self.binary), "process_executable_path_differs")
        _, binary_pin = _read_file(root / "exe", MAX_BINARY_BYTES, proc=True)
        argv_raw, _ = _read_file(root / "cmdline", MAX_PROCESS_BYTES, proc=True)
        environment_raw, _ = _read_file(root / "environ", MAX_PROCESS_BYTES, proc=True)
        argv, environment = parse_command_line(argv_raw), parse_selected_environment(environment_raw)
        _require(argv[0] == executable, "process_argv_executable_differs")
        stat_after, _ = _read_file(root / "stat", 16 * 1024, proc=True)
        _require(birth == parse_process_stat(stat_after, pid=pid), "process_generation_changed")
        boot_raw, _ = _read_file(Path("/proc/sys/kernel/random/boot_id"), 128, proc=True)
        boot_id = _decode(boot_raw, 128, "boot_id").strip()
        _require(re.fullmatch(r"[0-9a-f-]{36}", boot_id), "boot_id_format")
        return {**birth, "boot_id": boot_id, "executable": executable, "binary_pin": binary_pin,
                "command_line_sha256": _sha(argv_raw),
                "requested_launch_profile": parse_launch_profile(argv, environment),
                "selected_environment": environment}

    def inventory(self):
        files = {"header": self.root / "source/llama.cpp/include/llama.h",
                 "source_head": self.root / "source/llama.cpp/.git/HEAD",
                 "build_info": self.root / "build/common/build-info.cpp",
                 "common_defaults": self.root / "source/llama.cpp/common/common.h",
                 "argument_parser": self.root / "source/llama.cpp/common/arg.cpp",
                 "embedding_handler": self.root / "source/llama.cpp/tools/server/server-context.cpp"}
        pins, contents = {}, {}
        for key, path in files.items():
            contents[key], pins[key] = _read_file(path, MAX_SOURCE_BYTES)
        head = _decode(contents["source_head"], MAX_SOURCE_BYTES, "source_head").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            _require(re.fullmatch(r"refs/[A-Za-z0-9._/-]+", ref) and ".." not in ref.split("/"), "source_head_ref")
            raw, pins["source_head_ref"] = _read_file(self.root / "source/llama.cpp/.git" / ref, 128)
            head = _decode(raw, 128, "source_head_ref").strip()
        _require(re.fullmatch(r"[0-9a-f]{40}", head), "source_head_commit")
        build_text = _decode(contents["build_info"], MAX_SOURCE_BYTES, "build_info")
        commit = re.search(r'LLAMA_COMMIT\s*=\s*"([0-9a-f]{7,40})";', build_text)
        number = re.search(r"LLAMA_BUILD_NUMBER\s*=\s*([0-9]{1,9});", build_text)
        _require(commit is not None and number is not None, "build_info_fields")
        library = (self.root / "build/bin/libllama.so").resolve(strict=True)
        _require(library.parent == self.root / "build/bin", "native_library_path_differs")
        library_raw, pins["native_library"] = _read_file(library, MAX_BINARY_BYTES)
        exports = exported_api_inventory(library_raw)
        header = _decode(contents["header"], MAX_SOURCE_BYTES, "native_header")
        declarations = {name: bool(re.search(r"\bLLAMA_API\b[^;]{1,512}\b" + name + r"\s*\(", header))
                        for name in NATIVE_APIS}
        # The model is only statted. Its content remains explicitly unverified.
        model_info = os.stat(self.model)
        _require(stat.S_ISREG(model_info.st_mode), "model_path_file_type")
        return {"file_pins": pins, "source_commit": head,
                "build_info": "b" + number.group(1) + "-" + commit.group(1),
                "source_commit_matches_build_declaration": head.startswith(commit.group(1)),
                "native_api_declarations": declarations, "local_library_exports": exports,
                "model_path_stat": {"path": str(self.model), **_identity(model_info)},
                "library_exports_prove_loaded_process_execution": False}

    def transport(self, host):
        return discovery.NativeReadOnlyTransport("http://" + host + ":8080", timeout_seconds=2.0)


def _inspect(reader):
    result = {"schema": SCHEMA, "status": "unavailable", "diagnostic_complete": False,
              "observation_current": False, "qualified": False, "native_outputs_qualified": False,
              "native_execution_verified": False, "production_allowed": False,
              "model_content_hash_verified": False, "model_weights_read": False,
              "actual_native_output_dimension": None, "actual_execution_device": None,
              "embedding_requests": 0, "generation_requests": 0, "tokenizer_requests": 0,
              "service_or_configuration_changed": False, "training_executed": False,
              "execution_attestation": False, "proof_authority": False, "completion_authority": False,
              "transport_scope": "bounded_local_process_build_and_native_get_observations"
                  if type(reader) is _NativeReader else "controlled_protocol_only",
              "reason_codes": ["trusted_native_owner_integration_required"]}
    try:
        unit_before = reader.unit()
        process_before = reader.process(unit_before["MainPID"])
        profile = process_before["requested_launch_profile"]
        _require(profile["host"] in {"127.0.0.1", "172.17.0.1"} and profile["port"] == 8080,
                 "launch_service_origin_differs")
        _require(profile["model_alias"] == "leanstral_local" and profile["model_path"] == str(reader.model),
                 "launch_model_profile_differs")
        inventory_before = reader.inventory()
        observed = discovery.inspect_embedding_capability(reader.transport(profile["host"]))
        inventory_after = reader.inventory()
        unit_after = reader.unit()
        _require(unit_before == unit_after, "service_unit_generation_changed")
        process_after = reader.process(unit_after["MainPID"])
        _require(process_before == process_after, "process_generation_changed")
        _require(inventory_before == inventory_after, "build_source_or_model_metadata_changed")
        result.update(status="observed_prerequisites_only", diagnostic_complete=True, observation_current=True,
                      unit=unit_before, process=process_before, requested_launch_profile=profile,
                      native_build_inventory=inventory_before,
                      observed_native_input_dimension=observed["observed_native_input_dimension"],
                      observed_backend_build_info=observed["observed_backend_build_info"],
                      observed_context_allocation=observed["observed_context_allocation"],
                      response_pins=observed["response_pins"],
                      get_metadata_is_operation_owner_binding=False)
        if not profile["embedding_enabled_by_launch"]:
            result["reason_codes"].append("disabled_embeddings_requires_separate_owner")
        if profile["requested_pooling"] != "last":
            result["reason_codes"].append("last_pooling_requires_native_owner_verification")
        if not inventory_before["source_commit_matches_build_declaration"]:
            result["reason_codes"].append("source_build_declaration_differs")
        if not all(inventory_before["local_library_exports"].values()):
            result["reason_codes"].append("required_local_native_api_exports_missing")
        if observed["observed_backend_build_info"] != inventory_before["build_info"]:
            result["reason_codes"].append("get_build_and_local_build_declaration_differ")
        result["owner_blockers"] = ["operation_bound_native_entry_and_closing_callbacks",
                                    "independently_admitted_model_content_verification",
                                    "actual_native_output_width_pooling_and_untruncated_tokens",
                                    "actual_execution_device_and_microbatch_observation",
                                    "single_client_admission_cancellation_and_owned_cleanup"]
    except (DiagnosticUnavailable, OSError, ValueError, subprocess.SubprocessError) as exc:
        result["reason_codes"].append(str(exc) if type(exc) is DiagnosticUnavailable
                                      else "diagnostic_read_failed_" + type(exc).__name__)
    return result


def inspect_current_owner_prerequisites():
    """Observe the fixed current service; never authorize an embedding operation."""
    return _inspect(_NativeReader())
