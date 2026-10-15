"""Explicit bounded engineering builds of replayed V2 conditional projects.

Import performs no toolchain discovery or process execution. A build never
changes the preparation or supplies legal, review, training or admission
authority. Saved receipts describe historical observations, not fresh runs.
"""

from __future__ import annotations

import math
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import legal_corpus_definition_use_lake_v2 as preparation_owner

contracts = preparation_owner.contracts
SCHEMA = "legal-corpus-v2-definition-use-native-build/v1"
PROFILE = "bounded-v2-definition-use-conditional-build/v1"
MAX_CAPTURE_BYTES = 262144
MAX_BINARY_BYTES = 64 * 1024**2
MAX_MODULES = 6
RECEIPT_FILE = "build-receipt.json"
RUNNER_INTERFACE = "bounded-tool-runner/v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_EMPTY_AXIOMS = re.compile(
    r"(?:info: [^\r\n]{1,4096}:[0-9]{1,9}:[0-9]{1,9}: )?"
    r"'([^']+)' does not depend on any axioms"
)
_AXIOM_TEXT = re.compile(r"depends on axioms|does not depend on any axioms", re.I)
_FORBIDDEN = re.compile(r"\b(?:sorry|sorryAx|admit)\b")
_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    OSError,
    UnicodeError,
    RecursionError,
)
FALSE_FLAGS = dict.fromkeys(preparation_owner.review.FALSE_FLAGS, False)
for _technical_flag in ("backend_executed", "lean_compilation_verified"):
    FALSE_FLAGS.pop(_technical_flag, None)
FIELDS = {
    "profile",
    "preparation_cid",
    "preparation_manifest_sha256",
    "preparation_profile",
    "review_intake_binding",
    "review_evidence_status",
    "review_blockers",
    "review_prerequisites_satisfied_under_selected_trust",
    "toolchain",
    "binary_sha256",
    "version_probes",
    "producer_pins",
    "execution",
    "execution_limits",
    "execution_environment",
    "expected_modules",
    "expected_olean_paths",
    "conditional_theorems",
    "theorem_assumptions",
    "artifact_sha256",
    "artifact_bytes",
    "artifact_files",
    "compiled_modules",
    "manifest_coverage_passed",
    "theorem_axiom_dependencies",
    "axiom_report_valid",
    "post_run_validation_passed",
    "post_run_validation_error",
    "binaries_unchanged",
    "binary_recheck_error",
    "build_passed",
    "engineering_build_only",
    "lean_compilation_verified",
    "conditional_proofs_verified",
    "kernel_proofs_checked",
    "native_build_adapter_implemented",
    "admission_build_eligible",
    "toolchain_library_closure_verified",
    "toolchain_observation_scope",
    "backend_executed",
    *FALSE_FLAGS,
}


def _need(value, message):
    preparation_owner._need(value, message)


def _sha(raw):
    return preparation_owner._sha(raw)


def _pure_pins():
    path = Path(__file__).resolve()
    return preparation_owner._pure_pins() | {str(path): _sha(path.read_bytes())}


_IMPORTED_PINS = _pure_pins()
_OPERATION_PINS = None


def _owners():
    from ..backends import process
    from . import legal_corpus_lake, legal_pilot_lake

    return legal_pilot_lake, process, legal_corpus_lake


def _pins(owners):
    global _OPERATION_PINS
    pure = _pure_pins()
    _need(pure == _IMPORTED_PINS, "V2 build pure owners changed since import")
    extra = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in owners
    }
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(extra)
    _need(extra == _OPERATION_PINS, "V2 build runtime owners changed since first use")
    return pure | extra


def _limits(timeout):
    _need(
        type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 60,
        "finite bounded native build timeout required",
    )
    return {
        "timeout_seconds": timeout,
        "cpu_seconds": timeout,
        "resident_memory_bytes": 2 * 1024**3,
        "max_output_bytes": MAX_CAPTURE_BYTES,
        "max_input_bytes": preparation_owner.MAX_PROJECT_BYTES,
        "max_workspace_bytes": 128 * 1024**2,
        "max_output_files": MAX_MODULES,
    }


def _binary_expectations(expected, lake_executable=None):
    _need(
        type(expected) is dict and len(expected) == 2,
        "independently pinned native Lake and Lean binaries required",
    )
    for name, digest in expected.items():
        _need(
            type(name) is str
            and 0 < len(name) <= 4096
            and "\x00" not in name
            and Path(name).is_absolute()
            and ".." not in Path(name).parts
            and str(Path(name)) == name
            and type(digest) is str
            and _SHA.fullmatch(digest),
            "bounded absolute native binary paths and SHA256 pins required",
        )
    lakes = [Path(name) for name in expected if Path(name).name == "lake"]
    _need(
        len(lakes) == 1
        and set(expected) == {str(lakes[0]), str(lakes[0].parent / "lean")},
        "exact native Lake and sibling Lean pin population required",
    )
    if lake_executable is not None:
        _need(
            type(lake_executable) is str or isinstance(lake_executable, Path),
            "explicit native Lake path required",
        )
        _need(
            str(Path(lake_executable).absolute()) == str(lakes[0]),
            "native Lake path differs from independent binary expectations",
        )
    return lakes[0]


def _read_binary_pins(expected, transport):
    observed = {}
    for name in expected:
        path = Path(name)
        transport._check_directories(path.parent)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            _need(
                stat.S_ISREG(before.st_mode)
                and 4 <= before.st_size <= MAX_BINARY_BYTES
                and before.st_mode & 0o111,
                "bounded executable native ELF file required",
            )
            raw = source.read(MAX_BINARY_BYTES + 1)
            after = os.fstat(source.fileno())
            current = path.lstat()
            _need(
                transport._stable_stat(before)
                == transport._stable_stat(after)
                == transport._stable_stat(current)
                and len(raw) == before.st_size
                and raw[:4] == b"\x7fELF",
                "native executable changed or is not ELF",
            )
        observed[name] = _sha(raw)
    _need(observed == expected, "native binary differs from independent SHA256 pin")
    return observed


def _probes(probes, lake, toolchain):
    _need(
        type(probes) is dict and set(probes) == {"lake", "lean"},
        "exact native version probe population required",
    )
    expected = toolchain.removeprefix("leanprover/lean4:v")
    for label in ("lake", "lean"):
        row = probes[label]
        _need(
            type(row) is dict
            and set(row) == {"command", "stdout", "stderr", "returncode"},
            "closed native version observation required",
        )
        _need(
            row["command"] == [str(lake.parent / label), "--version"]
            and type(row["returncode"]) is int
            and row["returncode"] == 0,
            "native version command or exit mismatch",
        )
        _need(
            all(
                type(row[k]) is str and len(row[k].encode()) <= 16384
                for k in ("stdout", "stderr")
            ),
            "bounded native version diagnostics required",
        )
        found = re.findall(
            r"Lean \(?version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", row["stdout"]
        )
        _need(found == [expected], "native version differs from declared toolchain")


def _axioms(stdout, stderr, theorems):
    observed = {}
    valid = True
    for line in (stdout + "\n" + stderr).splitlines():
        if not _AXIOM_TEXT.search(line):
            continue
        match = _EMPTY_AXIOMS.fullmatch(line.strip())
        if not match or match[1] not in theorems or match[1] in observed:
            valid = False
        else:
            observed[match[1]] = []
    return observed, valid and set(observed) == set(theorems)


def _execution(result, process, paths):
    _need(
        process.BOUNDED_TOOL_RUNNER_VERSION == RUNNER_INTERFACE,
        "unsupported bounded runner implementation version",
    )
    _need(
        type(result) is process.ToolRunResult,
        "typed bounded runner observation required",
    )
    # A clipped UTF8 tail can become U+FFFD in the shared runner, adding two
    # encoded bytes. Retain that bounded failed observation verbatim.
    text_limit = MAX_CAPTURE_BYTES + (2 if result.output_truncated is True else 0)
    _need(
        type(result.stdout) is str
        and type(result.stderr) is str
        and len(result.stdout.encode()) <= text_limit
        and len(result.stderr.encode()) <= text_limit,
        "bounded compiler diagnostics required",
    )
    _need(
        isinstance(result.output_files, Mapping)
        and len(result.output_files) <= MAX_MODULES,
        "bounded runner output mapping required",
    )
    artifacts = dict(result.output_files)
    _need(
        len(artifacts) <= MAX_MODULES and set(artifacts) <= set(paths),
        "unexpected or unsafe native output path",
    )
    _need(
        all(
            type(raw) is bytes and len(raw) <= MAX_CAPTURE_BYTES
            for raw in artifacts.values()
        ),
        "bounded native output bytes required",
    )
    _need(
        type(result.runtime) is process.ToolRuntime,
        "typed native runtime observation required",
    )
    _need(
        type(result.command) is tuple
        and len(result.command) <= 8
        and all(type(part) is str and len(part) <= 4096 for part in result.command),
        "bounded observed command required",
    )
    _need(
        type(result.elapsed_seconds) in (int, float)
        and math.isfinite(result.elapsed_seconds)
        and result.elapsed_seconds >= 0,
        "finite observed runtime required",
    )
    _need(
        result.returncode is None or type(result.returncode) is int,
        "ordinary observed exit code required",
    )
    _need(
        result.pid is None or type(result.pid) is int, "ordinary observed PID required"
    )
    flags = (
        "timed_out",
        "cancelled",
        "unavailable",
        "output_truncated",
        "workspace_limit_exceeded",
        "process_tree_terminated",
        "resource_exhausted",
        "workspace_cleaned",
    )
    _need(
        all(type(getattr(result, key)) is bool for key in flags),
        "ordinary lifecycle flags required",
    )
    _need(
        all(
            type(getattr(result, key)) is str
            and len(getattr(result, key).encode()) <= 256
            for key in ("interface_version", "termination_reason")
        )
        and type(result.error) is str
        and len(result.error.encode()) <= text_limit,
        "bounded runner metadata required",
    )
    observation = {
        "interface_version": result.interface_version,
        "runtime": result.runtime.value,
        "command": list(result.command),
        "returncode": result.returncode,
        "pid": result.pid,
        "elapsed_seconds": result.elapsed_seconds,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "termination_reason": result.termination_reason,
        "error": result.error,
        **{key: getattr(result, key) for key in flags},
    }
    return observation, artifacts


def _receipt(
    checked,
    binary_pins,
    probes,
    producers,
    execution,
    limits,
    artifacts,
    post_error=None,
    binary_error=None,
):
    manifest = checked.to_dict()
    modules = manifest["expected_modules"]
    paths = manifest["execution_handoff"]["expected_olean_paths"]
    lake = _binary_expectations(binary_pins)
    command = [str(lake), "--offline", "--no-cache", "build", "legal"]
    axioms, axiom_valid = _axioms(
        execution["stdout"], execution["stderr"], manifest["conditional_theorems"]
    )
    coverage = set(artifacts) == set(paths) and all(artifacts.values())
    passed = bool(
        execution["interface_version"] == RUNNER_INTERFACE
        and execution["termination_reason"] == "completed"
        and execution["runtime"] in ("native", "kernel")
        and execution["command"] == command
        and type(execution["pid"]) is int
        and execution["pid"] > 0
        and execution["returncode"] == 0
        and not any(
            execution[key]
            for key in (
                "timed_out",
                "cancelled",
                "unavailable",
                "resource_exhausted",
                "output_truncated",
                "workspace_limit_exceeded",
            )
        )
        and execution["workspace_cleaned"]
        and not execution["error"]
        and not _FORBIDDEN.search(execution["stdout"] + execution["stderr"])
        and coverage
        and axiom_valid
        and post_error is None
        and binary_error is None
    )
    value = contracts.seal_record(
        {
            "schema": SCHEMA,
            "profile": PROFILE,
            "preparation_cid": manifest["record_cid"],
            "preparation_manifest_sha256": _sha(checked.manifest_json.encode()),
            "preparation_profile": manifest["profile"],
            **{
                key: manifest[key]
                for key in (
                    "review_intake_binding",
                    "review_evidence_status",
                    "review_blockers",
                    "review_prerequisites_satisfied_under_selected_trust",
                    "toolchain",
                    "conditional_theorems",
                    "theorem_assumptions",
                )
            },
            "binary_sha256": binary_pins,
            "version_probes": probes,
            "producer_pins": producers,
            "execution": execution,
            "execution_limits": limits,
            "execution_environment": {
                "ELAN_TOOLCHAIN": manifest["toolchain"],
                "LEAN_NUM_THREADS": "1",
            },
            "expected_modules": modules,
            "expected_olean_paths": paths,
            "artifact_sha256": {name: _sha(raw) for name, raw in artifacts.items()},
            "artifact_bytes": {name: len(raw) for name, raw in artifacts.items()},
            "artifact_files": {
                name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                for name in artifacts
            },
            "compiled_modules": [
                module
                for module, path in zip(modules, paths, strict=True)
                if path in artifacts
            ],
            "manifest_coverage_passed": bool(coverage),
            "theorem_axiom_dependencies": axioms,
            "axiom_report_valid": axiom_valid,
            "post_run_validation_passed": post_error is None,
            "post_run_validation_error": post_error,
            "binaries_unchanged": binary_error is None,
            "binary_recheck_error": binary_error,
            "build_passed": passed,
            "backend_executed": type(execution["pid"]) is int and execution["pid"] > 0,
            "engineering_build_only": True,
            "lean_compilation_verified": passed,
            "conditional_proofs_verified": passed,
            "kernel_proofs_checked": passed,
            "native_build_adapter_implemented": True,
            "admission_build_eligible": False,
            "toolchain_library_closure_verified": False,
            "toolchain_observation_scope": "Two independently pinned native binaries and matching bounded version probes; no installed library/distribution or loaded-code attestation.",
            **FALSE_FLAGS,
        }
    )
    raw = canonical_dag_json_bytes(value)
    _need(
        len(raw) <= contracts.MAX_RECORD_BYTES,
        "complete native build receipt exceeds record bound",
    )
    return value


def _error(error):
    return {"type": type(error).__name__, "message": str(error)[:2048]}


def _write_bundle(output, checked, receipt, artifacts, transport):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    transport._check_directories(output)
    expected = {name: body.encode() for name, body in checked.files}
    expected[transport.MANIFEST_FILE] = checked.manifest_json.encode()

    def readback(root, raw):
        _need(
            raw == expected[transport.MANIFEST_FILE]
            and transport._read_files(
                root, set(expected), maximum_files=preparation_owner.MAX_FILES
            )
            == expected,
            "frozen executed project differs from exact inputs",
        )

    transport._write_project(
        checked,
        output / "project",
        readback=readback,
        maximum_files=preparation_owner.MAX_FILES,
    )
    compiled = output / "compiled"
    compiled.mkdir(mode=0o700, exist_ok=False)
    fd = os.open(compiled, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    descriptors = {"": fd}
    shortened = {
        name.removeprefix(".lake/build/lib/lean/"): raw
        for name, raw in artifacts.items()
    }
    try:
        for name, raw in shortened.items():
            dirname, _, basename = name.rpartition("/")
            if dirname and dirname not in descriptors:
                os.mkdir(dirname, mode=0o700, dir_fd=fd)
                descriptors[dirname] = os.open(
                    dirname, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=fd
                )
            transport._write_new_file(descriptors[dirname], basename, raw)
        for descriptor in descriptors.values():
            os.fsync(descriptor)
    finally:
        for descriptor in reversed(list(descriptors.values())):
            os.close(descriptor)
    _need(
        transport._read_files(compiled, set(shortened), maximum_files=MAX_MODULES)
        == shortened,
        "compiled artifacts failed exact readback",
    )
    fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        transport._check_directories(output, fd)
        raw = canonical_dag_json_bytes(receipt)
        transport._write_new_file(fd, RECEIPT_FILE, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    _need(
        _read_receipt(output, transport) == raw, "native receipt failed exact readback"
    )


def _read_receipt(directory, transport):
    transport._check_directories(directory)
    fd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        transport._check_directories(directory, fd)
        rows = {}
        with os.scandir(fd) as entries:
            for entry in entries:
                rows[entry.name] = (
                    entry.is_symlink(),
                    entry.is_dir(follow_symlinks=False),
                )
                _need(len(rows) <= 3, "unexpected native build bundle entry")
        _need(
            set(rows) == {RECEIPT_FILE, "project", "compiled"}
            and all(not row[0] for row in rows.values())
            and rows["project"][1]
            and rows["compiled"][1]
            and not rows[RECEIPT_FILE][1],
            "closed ordinary native build bundle required",
        )
        source_fd = os.open(
            RECEIPT_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        with os.fdopen(source_fd, "rb") as source:
            before = os.fstat(source.fileno())
            _need(
                stat.S_ISREG(before.st_mode)
                and before.st_size <= contracts.MAX_RECORD_BYTES,
                "bounded ordinary build receipt required",
            )
            raw = source.read(contracts.MAX_RECORD_BYTES + 1)
            after = os.fstat(source.fileno())
            current = os.stat(RECEIPT_FILE, dir_fd=fd, follow_symlinks=False)
            _need(
                transport._stable_stat(before)
                == transport._stable_stat(after)
                == transport._stable_stat(current)
                and len(raw) == before.st_size,
                "native build receipt changed while reading",
            )
        transport._check_directories(directory, fd)
        return raw
    finally:
        os.close(fd)


def build_definition_use_corpus_v2(
    preparation,
    assessment_raw,
    *,
    expected_assessment_file_sha256,
    review_inputs,
    toolchain,
    lake_executable,
    expected_binary_sha256,
    output_directory,
    timeout_seconds=60,
    cancellation=None,
):
    """Run an explicit candidate engineering build; callers own the validation lease."""
    limits = _limits(timeout_seconds)
    lake = _binary_expectations(expected_binary_sha256, lake_executable)
    expected_binary_sha256 = dict(expected_binary_sha256)
    _need(_pure_pins() == _IMPORTED_PINS, "V2 build pure owners changed since import")
    validation = {
        "expected_assessment_file_sha256": expected_assessment_file_sha256,
        "review_inputs": review_inputs,
        "toolchain": toolchain,
    }
    checked = preparation_owner.validate_definition_use_corpus_v2(
        preparation, assessment_raw, **validation
    )
    owners = _owners()
    pilot, process, transport = owners
    producers = _pins(owners)
    output = transport._path(output_directory)
    transport._check_directories(output.parent, allow_missing=True)
    _need(
        not output.exists() and not output.is_symlink(),
        "fresh native build output directory required",
    )
    _need(
        not process._is_cancelled(cancellation),
        "native build cancelled before version probes",
    )
    _read_binary_pins(expected_binary_sha256, transport)
    executable, binaries, probes = pilot._installed_toolchain(str(lake), toolchain)
    _need(
        executable == lake and binaries == expected_binary_sha256,
        "native toolchain differs from independent pins",
    )
    _probes(probes, lake, toolchain)
    _read_binary_pins(expected_binary_sha256, transport)
    _need(
        _pins(owners) == producers, "native build owners changed during version probes"
    )
    # Version probes execute processes too: replay again before launching Lake.
    preparation_owner.validate_definition_use_corpus_v2(
        checked, assessment_raw, **validation
    )
    _need(
        not process._is_cancelled(cancellation),
        "native build cancelled before Lake execution",
    )
    manifest = checked.to_dict()
    paths = manifest["execution_handoff"]["expected_olean_paths"]
    _need(
        len(paths) == len(manifest["expected_modules"]) == MAX_MODULES,
        "closed six-module V2 build population required",
    )
    command = (str(lake), "--offline", "--no-cache", "build", "legal")
    result = process.BoundedToolRunner().run(
        process.ToolRunRequest(
            argv=command,
            input_files=dict(checked.files),
            output_paths=tuple(paths),
            environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"},
            limits=process.ToolRunLimits(**limits),
        ),
        **({"cancellation": cancellation} if cancellation is not None else {}),
    )
    execution, artifacts = _execution(result, process, paths)
    post_error = binary_error = None
    try:
        preparation_owner.validate_definition_use_corpus_v2(
            checked, assessment_raw, **validation
        )
        _need(
            _pins(owners) == producers, "native build owners changed during execution"
        )
    except _ERRORS as error:
        post_error = _error(error)
    try:
        _read_binary_pins(expected_binary_sha256, transport)
    except _ERRORS as error:
        binary_error = _error(error)
    receipt = _receipt(
        checked,
        dict(expected_binary_sha256),
        probes,
        producers,
        execution,
        limits,
        artifacts,
        post_error,
        binary_error,
    )
    _write_bundle(output, checked, receipt, artifacts, transport)
    return receipt


def load_definition_use_build_v2(
    directory,
    preparation,
    assessment_raw,
    *,
    expected_receipt_sha256,
    expected_assessment_file_sha256,
    review_inputs,
    toolchain,
    expected_binary_sha256,
):
    """Replay saved custody without probing binaries or rerunning the compiler.

    The externally trusted receipt pin establishes historical observation
    custody. A self-resealed producer report alone cannot establish execution.
    """
    lake = _binary_expectations(expected_binary_sha256)
    expected_binary_sha256 = dict(expected_binary_sha256)
    _need(_pure_pins() == _IMPORTED_PINS, "V2 build pure owners changed since import")
    validation = {
        "expected_assessment_file_sha256": expected_assessment_file_sha256,
        "review_inputs": review_inputs,
        "toolchain": toolchain,
    }
    checked = preparation_owner.validate_definition_use_corpus_v2(
        preparation, assessment_raw, **validation
    )
    owners = _owners()
    transport = owners[2]
    producers = _pins(owners)
    root = transport._path(directory)
    raw = _read_receipt(root, transport)
    receipt = contracts.load_record_bytes(raw, expected_sha256=expected_receipt_sha256)
    contracts.validate_record(receipt, schema=SCHEMA, fields=FIELDS)
    _need(
        receipt["binary_sha256"] == expected_binary_sha256
        and receipt["producer_pins"] == producers,
        "saved native build binary or producer expectations differ",
    )
    _probes(receipt["version_probes"], lake, toolchain)
    execution = receipt["execution"]
    _need(type(execution) is dict, "closed saved execution observation required")
    process = owners[1]
    fields = dict(execution)
    fields["runtime"] = process.ToolRuntime(fields["runtime"])
    fields["command"] = tuple(fields["command"])
    artifact_names = receipt["artifact_files"]
    paths = checked.to_dict()["execution_handoff"]["expected_olean_paths"]
    _need(
        type(artifact_names) is dict
        and set(artifact_names) <= set(paths)
        and all(
            value == "compiled/" + name.removeprefix(".lake/build/lib/lean/")
            for name, value in artifact_names.items()
        ),
        "closed saved artifact population required",
    )
    names = {value.removeprefix("compiled/") for value in artifact_names.values()}
    captured = transport._read_files(
        root / "compiled", names, maximum_files=MAX_MODULES
    )
    artifacts = {
        name: captured[value.removeprefix("compiled/")]
        for name, value in artifact_names.items()
    }
    fields["output_files"] = artifacts
    try:
        result = process.ToolRunResult(**fields)
    except TypeError as error:
        raise contracts.CorpusContractError(
            "closed saved runner observation required"
        ) from error
    observation, artifacts = _execution(result, process, paths)
    for key in ("post_run_validation_error", "binary_recheck_error"):
        error = receipt[key]
        _need(
            error is None
            or (
                type(error) is dict
                and set(error) == {"type", "message"}
                and all(
                    type(value) is str and len(value) <= 2048
                    for value in error.values()
                )
            ),
            "bounded saved qualification error required",
        )
    expected = _receipt(
        checked,
        dict(expected_binary_sha256),
        receipt["version_probes"],
        producers,
        observation,
        _limits(receipt["execution_limits"]["timeout_seconds"]),
        artifacts,
        receipt["post_run_validation_error"],
        receipt["binary_recheck_error"],
    )
    _need(
        receipt == expected and raw == canonical_dag_json_bytes(expected),
        "saved native build receipt differs from independent reconstruction",
    )
    preparation_owner.load_definition_use_corpus_v2(
        root / "project",
        assessment_raw,
        expected_manifest_sha256=_sha(checked.manifest_json.encode()),
        **validation,
    )
    _need(
        _pins(owners) == producers, "native build owners changed during saved readback"
    )
    return receipt


__all__ = ["build_definition_use_corpus_v2", "load_definition_use_build_v2"]
