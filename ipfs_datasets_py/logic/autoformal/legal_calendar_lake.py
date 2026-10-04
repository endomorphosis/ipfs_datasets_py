"""Native Lean gate for explicitly interpreted Gregorian and duration rules.

Every qualifier needs a source/candidate-bound interpretation sidecar. A build
checks the declared interpretation, never whether legislation has that meaning.
The original unqualified gate and its evidence remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from . import legal_pilot_lake as old
from . import legal_canonical_calendar as bridge
from ..backends import process
from ..formalization.autoencoder import native_family_lean_emitters as emitters
from ..formalization.autoencoder import native_legal_qualified_lean as native
from ..formalization.autoencoder import native_qualified_lean as qualified
from ..legal_ir import canonical_contracts as contracts

SCHEMA = "legal-explicit-calendar-lake/v1"
PROFILE = "canonical-explicit-calendar/v1"
MAX_ROWS = old.MAX_ROWS
_json, _sha = old._json, old._sha
_LAKEFILE = ('name = "legal_calendar"\nversion = "0.1.0"\n\n'
             '[[lean_lib]]\nname = "legal"\nroots = ["LegalCalendar"]\n')
_SCOPE = {
    "admitted": False, "formalized": False, "source_semantics_verified": False,
    "proof_authority": False, "all_logic_families_supported": False,
    "supported_family_profiles": ["deontic/" + PROFILE, "deontic/canonical-explicit-qualified/v1"],
    "scope": "Compilation under explicit caller interpretations; no legal-source fidelity or truth assertion.",
}


def _pins():
    return {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
            for module in (old, bridge, process, emitters, native, qualified, contracts)} | {
                str(Path(__file__).resolve()): _sha(Path(__file__).read_bytes())} | bridge.producer_pins()


_IMPORTED_PINS = _pins()


@dataclass(frozen=True)
class QualifiedPreparation:
    manifest_json: str
    input_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        return json.loads(self.manifest_json)


@dataclass(frozen=True)
class QualifiedReceipt:
    receipt_json: str

    def to_dict(self):
        return json.loads(self.receipt_json)


def _inputs(rows):
    if type(rows) not in (list, tuple) or not 0 < len(rows) <= MAX_ROWS:
        raise ValueError(f"rows must contain 1..{MAX_ROWS} candidates")
    for row in rows:
        if type(row) is not dict or set(row) != {"candidate", "interpretation"}:
            raise ValueError("candidate and explicit interpretation fields required")
        if type(row["candidate"]) is not dict or set(row["candidate"]) != {
                "candidate_id", "source_text", "source_sha256", "canonical_ir"}:
            raise ValueError("exact candidate fields required")
    # Source hash, canonical roundtrip, order, uniqueness and byte limits are
    # checked before any candidate is classified as supported/unsupported.
    old._bounded_rows([row["candidate"] for row in rows])
    raw = _json(rows)
    if len(raw.encode("utf-8")) > old.MAX_INPUT_BYTES:
        raise ValueError("candidate and interpretation batch exceeds byte bound")
    return json.loads(raw)


def prepare_qualified_legal(rows, *, toolchain):
    if type(toolchain) is not str or not old._TOOLCHAIN.fullmatch(toolchain):
        raise ValueError("explicit version-pinned Lean toolchain required")
    if _pins() != _IMPORTED_PINS:
        raise ValueError("calendar gate producer changed since import")
    inputs = _inputs(rows)
    files = {
        "lakefile.toml": _LAKEFILE, "lean-toolchain": toolchain + "\n",
        "LegalCalendar/Prelude.lean": "namespace LegalCalendar\n" + emitters.PRELUDE + "\nend LegalCalendar\n",
    }
    candidates, imports = [], []
    for index, entry in enumerate(inputs):
        candidate = entry["candidate"]
        record = {"candidate_id": candidate["candidate_id"], "source_sha256": candidate["source_sha256"],
                  "canonical_ir_sha256": _sha(_json(candidate["canonical_ir"])),
                  "interpretation_sha256": _sha(_json(entry["interpretation"])),
                  "family": "deontic", "profile": PROFILE, "status": "unsupported", "module": None}
        try:
            result = bridge.prepare_canonical_qualified(candidate, entry["interpretation"])
            body = result["lean_body"]
            if old._REFUSED.search(body):
                raise ValueError("refused Lean keyword or placeholder in emitted source")
            module = f"LegalCalendar.Candidate{index:04d}"
            content = f"import LegalCalendar.Prelude\nnamespace {module}\n{body}\nend {module}\n"
            files[module.replace(".", "/") + ".lean"] = content
            imports.append("import " + module)
            record.update(status="supported", module=module, lean_sha256=_sha(content),
                          profile=result["lowering_details"]["supported_family_profile"].split("/", 1)[1],
                          bridge_sha256=_sha(_json(result)), lowering=result["lowering_details"])
        except (ValueError, TypeError, KeyError) as error:
            record["reason"] = str(error)
        candidates.append(record)
    supported = all(row["status"] == "supported" for row in candidates)
    if supported:
        files["LegalCalendar.lean"] = "\n".join(imports) + "\n"
    else:
        files = {}
    raw = _json(inputs)
    files["qualified-inputs.json"] = raw + "\n"
    manifest = {"schema": SCHEMA, "toolchain": toolchain, "target": "legal",
                "status": "prepared" if supported else "blocked", "backend_executed": False,
                "all_candidates_supported": supported, "candidates": candidates,
                "input_sha256": _sha(raw), "producer_pins": dict(_IMPORTED_PINS),
                "file_sha256": {name: _sha(body) for name, body in sorted(files.items())}, **_SCOPE}
    return QualifiedPreparation(_json(manifest), raw, tuple(sorted(files.items())))


def validate_preparation(preparation):
    if type(preparation) is not QualifiedPreparation:
        raise ValueError("QualifiedPreparation required")
    expected = prepare_qualified_legal(json.loads(preparation.input_json), toolchain=preparation.to_dict()["toolchain"])
    if expected != preparation:
        raise ValueError("candidate, interpretation, files or import coverage changed")


def build_qualified_legal(rows, *, toolchain, lake_executable, timeout_seconds=60, output_directory=None):
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be in (0, 60]")
    output = Path(output_directory).resolve() if output_directory is not None else None
    if output is not None and output.exists():
        raise ValueError("fresh output_directory required")
    preparation = prepare_qualified_legal(rows, toolchain=toolchain)
    validate_preparation(preparation)
    receipt = preparation.to_dict()
    receipt.update(build_passed=False, manifest_coverage_passed=False, compiled_modules=[],
                   command=None, returncode=None)
    if receipt["all_candidates_supported"]:
        executable, binaries, probes = old._installed_toolchain(lake_executable, toolchain)
        command = (str(executable), "build", "legal")
        modules = ["LegalCalendar.Prelude", *(row["module"] for row in receipt["candidates"]), "LegalCalendar"]
        paths = tuple(".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules)
        result = process.BoundedToolRunner().run(process.ToolRunRequest(
            argv=command, input_files=dict(preparation.files), output_paths=paths,
            environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "2"},
            limits=process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
                resident_memory_bytes=2 * 1024**3, max_output_bytes=262_144, max_input_bytes=8 * 1024**2,
                max_workspace_bytes=128 * 1024**2, max_output_files=MAX_ROWS + 2)))
        validate_preparation(preparation)
        binary_match = all(_sha(Path(name).read_bytes()) == digest for name, digest in binaries.items())
        artifacts = {name: _sha(raw) for name, raw in result.output_files.items()}
        coverage = set(artifacts) == set(paths)
        passed = (result.ok and not result.output_truncated and not result.workspace_limit_exceeded
                  and coverage and binary_match and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
        receipt.update(status="passed" if passed else "failed", backend_executed=result.pid is not None,
            build_passed=passed, manifest_coverage_passed=coverage,
            compiled_modules=[name for name, path in zip(modules, paths) if path in artifacts],
            command=list(command), command_sha256=_sha(_json(list(command))), binary_sha256=binaries,
            binary_pins_match=binary_match, version_probe=probes, returncode=result.returncode,
            artifact_sha256=artifacts, stdout=result.stdout, stderr=result.stderr,
            stdout_sha256=_sha(result.stdout), stderr_sha256=_sha(result.stderr),
            timed_out=result.timed_out, output_truncated=result.output_truncated,
            workspace_limit_exceeded=result.workspace_limit_exceeded, resource_exhausted=result.resource_exhausted,
            unavailable=result.unavailable, cancelled=result.cancelled, workspace_cleaned=result.workspace_cleaned,
            process_tree_terminated=result.process_tree_terminated, error=result.error,
            execution_environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "2"},
            execution_limits={"timeout_seconds": timeout_seconds, "cpu_seconds": timeout_seconds,
                "sampled_tree_rss_bytes": 2 * 1024**3, "max_workspace_bytes": 128 * 1024**2})
    receipt["receipt_sha256"] = _sha(_json(receipt))
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
        files = dict(preparation.files) | {"qualified-manifest.json": preparation.manifest_json + "\n",
                                          "qualified-receipt.json": _json(receipt) + "\n"}
        for name, body in files.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(body)
    return QualifiedReceipt(_json(receipt))


__all__ = ["prepare_qualified_legal", "validate_preparation", "build_qualified_legal",
           "QualifiedPreparation", "QualifiedReceipt", "PROFILE", "SCHEMA", "MAX_ROWS"]
