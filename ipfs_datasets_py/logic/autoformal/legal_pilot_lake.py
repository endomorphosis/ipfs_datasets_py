"""Source-bound compilation gate for the exact command ``lake build legal``.

The supported fragment is the native, unqualified canonical O/P/F profile.
Predicates and modalities remain interpretation parameters. Compilation checks
the representation, never correspondence to legislation or proposition truth.
Qualified/unsupported rows block the whole batch rather than disappearing from
its build target. No downloads or toolchain selection are performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ..backends import process
from ..formalization.autoencoder import native_family_lean_emitters as emitters
from ..legal_ir import canonical_contracts as contracts

SCHEMA = "legal-pilot-lake/v1"
PROFILE = "canonical-unqualified/v1"
MAX_ROWS = 128
MAX_SOURCE_BYTES = 65_536
MAX_INPUT_BYTES = 4 * 1024 * 1024
_TOOLCHAIN = re.compile(r"leanprover/lean4:v(\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)\Z")
_REFUSED = re.compile(r"\b(?:sorry|admit|sorryAx|axiom|unsafe)\b")
_LAKEFILE = ('name = "legal_pilot"\nversion = "0.1.0"\n\n'
             '[[lean_lib]]\nname = "legal"\nroots = ["LegalPilot"]\n')
_DISCLAIMERS = {
    "admitted": False, "formalized": False, "source_semantics_verified": False,
    "proof_authority": False, "supported_family_profiles": ["deontic/" + PROFILE],
    "scope": "Compiled parameterized representations; no legal-semantic qualification or source-truth proof.",
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _producer_pins() -> dict[str, str]:
    return {str(Path(name).resolve()): _sha(Path(name).read_bytes())
            for name in (__file__, emitters.__file__, contracts.__file__, process.__file__)}


_IMPORTED_PINS = _producer_pins()


@dataclass(frozen=True)
class LegalPilotPreparation:
    """Immutable prepared files and manifest; preparation is not execution."""

    manifest_json: str
    input_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.manifest_json)


@dataclass(frozen=True)
class LegalPilotReceipt:
    """Immutable serialized observation; copies are not an admission token."""

    receipt_json: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.receipt_json)


def _bounded_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(rows, (list, tuple)) or not 0 < len(rows) <= MAX_ROWS:
        raise ValueError(f"rows must contain 1..{MAX_ROWS} candidates")
    # Reject extra metadata rather than accidentally giving it evidentiary status.
    required = {"candidate_id", "source_text", "source_sha256", "canonical_ir"}
    result, identifiers = [], set()
    for row in rows:
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {"family", "profile"}:
            raise ValueError("candidate fields changed")
        identity, source = row["candidate_id"], row["source_text"]
        if type(identity) is not str or not identity.strip() or len(identity) > 256 or identity in identifiers:
            raise ValueError("bounded unique candidate_id required")
        identifiers.add(identity)
        if type(source) is not str or not source.strip() or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("bounded nonempty source_text required")
        if row["source_sha256"] != _sha(source):
            raise ValueError("source_sha256 differs from exact source_text UTF-8 bytes")
        ir = row["canonical_ir"]
        if type(ir) is not dict or type(ir.get("rules")) is not list or not 0 < len(ir["rules"]) <= 64:
            raise ValueError("bounded nonempty canonical rules required")
        if len(_json(ir).encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("canonical_ir exceeds byte bound")
        native = contracts.CanonicalRoundTripIR.from_dict(ir)
        if native.to_dict() != ir:
            raise ValueError("exact canonical IR roundtrip required (including rule order)")
        result.append({**row, "family": row.get("family", "deontic"),
                       "profile": row.get("profile", PROFILE)})
    raw = _json(result)
    if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("candidate batch exceeds byte bound")
    return json.loads(raw)


def prepare_legal_pilot(rows: Sequence[Mapping[str, Any]], *, toolchain: str) -> LegalPilotPreparation:
    """Emit deterministic native declarations for an explicitly bounded profile."""
    if not isinstance(toolchain, str) or not _TOOLCHAIN.fullmatch(toolchain):
        raise ValueError("explicit version-pinned leanprover/lean4:vX.Y.Z toolchain required")
    if _producer_pins() != _IMPORTED_PINS:
        raise ValueError("pilot producer changed since import")
    inputs = _bounded_rows(rows)
    files = {
        "lakefile.toml": _LAKEFILE,
        "lean-toolchain": toolchain + "\n",
        "LegalPilot/Prelude.lean": "namespace LegalPilot\n" + emitters.PRELUDE + "\nend LegalPilot\n",
    }
    candidates, imports = [], []
    for index, row in enumerate(inputs):
        record = {"candidate_id": row["candidate_id"], "source_sha256": row["source_sha256"],
                  "canonical_ir_sha256": _sha(_json(row["canonical_ir"])),
                  "family": row["family"], "profile": row["profile"],
                  "status": "unsupported", "module": None}
        try:
            if row["family"] != "deontic" or row["profile"] != PROFILE:
                raise emitters.UnsupportedNativeLean("only deontic canonical-unqualified/v1 is supported")
            body, lowering = emitters.canonical_norms(row["canonical_ir"])
            # This deliberately also refuses reserved words in symbols: the
            # pilot has a conservative printable-symbol subset, not a lexer.
            if _REFUSED.search(body):
                raise emitters.UnsupportedNativeLean("refused Lean keyword or placeholder in emitted source")
            module = f"LegalPilot.Candidate{index:04d}"
            content = ("import LegalPilot.Prelude\n"
                       f"namespace {module}\n{body}\nend {module}\n")
            files[module.replace(".", "/") + ".lean"] = content
            imports.append("import " + module)
            record.update(status="supported", module=module, lean_sha256=_sha(content), lowering=lowering)
        except emitters.UnsupportedNativeLean as exc:
            record["reason"] = str(exc)
        candidates.append(record)
    supported = all(row["status"] == "supported" for row in candidates)
    if supported:
        files["LegalPilot.lean"] = "\n".join(imports) + "\n"
    else:
        # Do not leave a runnable project that could compile only a subset.
        files = {}
    input_json = _json(inputs)
    files["pilot-inputs.json"] = input_json + "\n"
    manifest = {"schema": SCHEMA, "toolchain": toolchain, "target": "legal",
                "status": "prepared" if supported else "blocked",
                "backend_executed": False, "all_candidates_supported": supported,
                "candidates": candidates, "input_sha256": _sha(input_json),
                "producer_pins": dict(_IMPORTED_PINS),
                "file_sha256": {name: _sha(body) for name, body in sorted(files.items())},
                **_DISCLAIMERS}
    return LegalPilotPreparation(_json(manifest), input_json, tuple(sorted(files.items())))


def validate_legal_pilot_preparation(preparation: LegalPilotPreparation) -> None:
    """Replay all bound inputs; refuse changed source, hashes or import coverage."""
    if not isinstance(preparation, LegalPilotPreparation):
        raise ValueError("LegalPilotPreparation required")
    manifest = preparation.to_dict()
    regenerated = prepare_legal_pilot(json.loads(preparation.input_json), toolchain=manifest["toolchain"])
    if preparation != regenerated:
        raise ValueError("prepared files, canonical bindings or manifest coverage changed")


def _installed_toolchain(lake_executable: str, toolchain: str) -> tuple[Path, dict[str, str], dict[str, Any]]:
    executable = Path(lake_executable).expanduser().absolute()
    # Native binaries avoid elan downloading or replacing the pinned compiler.
    if not executable.is_file() or executable.is_symlink() or not executable.read_bytes()[:4] == b"\x7fELF":
        raise ValueError("explicit installed native Lake ELF executable required")
    lean = executable.parent / "lean"
    if not lean.is_file() or lean.is_symlink() or not lean.read_bytes()[:4] == b"\x7fELF":
        raise ValueError("installed sibling Lean ELF executable required")
    pins = {str(path): _sha(path.read_bytes()) for path in (executable, lean)}
    runtime = process.BoundedToolRunner()
    expected = _TOOLCHAIN.fullmatch(toolchain).group(1)
    probes = {}
    for name, path in (("lake", executable), ("lean", lean)):
        version = runtime.run(process.ToolRunRequest(
            argv=(str(path), "--version"),
            limits=process.ToolRunLimits(timeout_seconds=5, max_output_bytes=16_384)))
        match = re.search(r"Lean \(?version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", version.stdout)
        if not version.ok or version.output_truncated or not match or match.group(1) != expected:
            raise ValueError("installed " + name + " version does not match explicit toolchain")
        probes[name] = {"command": list(version.command), "stdout": version.stdout,
                        "stderr": version.stderr, "returncode": version.returncode}
    return executable, pins, probes


def build_legal_pilot(
    rows: Sequence[Mapping[str, Any]], *, toolchain: str, lake_executable: str,
    timeout_seconds: float = 60, output_directory: str | Path | None = None,
) -> LegalPilotReceipt:
    """Actually run the lowercase target; persist a rerunnable project if asked.

    ``output_directory`` must be new. The receipt binds exact emitted source,
    canonical candidates, source text, binaries, command and output hashes.
    Existing files are never overwritten. Failed execution is an observation,
    while malformed requests raise ValueError.
    """
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be in (0, 60]")
    output = Path(output_directory).resolve() if output_directory is not None else None
    if output is not None and output.exists():
        raise ValueError("fresh output_directory required")
    preparation = prepare_legal_pilot(rows, toolchain=toolchain)
    validate_legal_pilot_preparation(preparation)
    receipt = preparation.to_dict()
    receipt.update(build_passed=False, manifest_coverage_passed=False,
                   compiled_modules=[], dependencies=[], command=None, returncode=None)
    if receipt["all_candidates_supported"]:
        executable, binary_pins, version_probe = _installed_toolchain(lake_executable, toolchain)
        command = (str(executable), "build", "legal")
        modules = ["LegalPilot.Prelude", *(row["module"] for row in receipt["candidates"]), "LegalPilot"]
        artifacts = tuple(".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" for module in modules)
        result = process.BoundedToolRunner().run(process.ToolRunRequest(
            argv=command, input_files=dict(preparation.files), output_paths=artifacts,
            environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "2"},
            limits=process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
                                        resident_memory_bytes=2 * 1024**3, max_output_bytes=262_144,
                                        max_input_bytes=8 * 1024**2, max_workspace_bytes=128 * 1024**2,
                                        max_output_files=MAX_ROWS + 2)))
        validate_legal_pilot_preparation(preparation)
        binary_pins_match = all(_sha(Path(name).read_bytes()) == digest for name, digest in binary_pins.items())
        outputs = {name: _sha(raw) for name, raw in result.output_files.items()}
        coverage = set(outputs) == set(artifacts)
        passed = (result.ok and not result.output_truncated and not result.workspace_limit_exceeded
                  and coverage and binary_pins_match
                  and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
        receipt.update(status="passed" if passed else "failed", backend_executed=result.pid is not None,
                       build_passed=passed, manifest_coverage_passed=coverage,
                       compiled_modules=[module for module, path in zip(modules, artifacts) if path in outputs],
                       command=list(command), command_sha256=_sha(_json(list(command))),
                       binary_sha256=binary_pins, binary_pins_match=binary_pins_match,
                       version_probe=version_probe, returncode=result.returncode,
                       execution_environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "2"},
                       execution_limits={"timeout_seconds": timeout_seconds, "cpu_seconds": timeout_seconds,
                                         "sampled_tree_rss_bytes": 2 * 1024**3, "max_output_bytes": 262_144,
                                         "max_input_bytes": 8 * 1024**2, "max_workspace_bytes": 128 * 1024**2},
                       stdout=result.stdout, stderr=result.stderr,
                       stdout_sha256=_sha(result.stdout), stderr_sha256=_sha(result.stderr),
                       artifact_sha256=outputs, timed_out=result.timed_out,
                       output_truncated=result.output_truncated,
                       workspace_limit_exceeded=result.workspace_limit_exceeded,
                       resource_exhausted=result.resource_exhausted, unavailable=result.unavailable,
                       workspace_cleaned=result.workspace_cleaned, cancelled=result.cancelled,
                       process_tree_terminated=result.process_tree_terminated, error=result.error)
    # The checksum is tamper-evident, not a signature or admission authority.
    receipt["receipt_sha256"] = _sha(_json(receipt))
    rendered = _json(receipt)
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
        for name, body in preparation.files:
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                handle.write(body)
        for name, body in (("pilot-manifest.json", preparation.manifest_json), ("pilot-receipt.json", rendered)):
            with (output / name).open("x", encoding="utf-8") as handle:
                handle.write(body + "\n")
    return LegalPilotReceipt(rendered)


__all__ = ["LegalPilotPreparation", "LegalPilotReceipt", "prepare_legal_pilot",
           "validate_legal_pilot_preparation", "build_legal_pilot", "PROFILE", "SCHEMA"]
