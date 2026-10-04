"""Compile regenerated source-bound family adapters with ``lake build legal``.

The caller supplies a candidate, an explicit interpretation and exact source
occurrences. Emitted Lean is never accepted as an input. A successful receipt
checks the declared adapter structure; it does not adjudicate legal meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from . import legal_pilot_lake as shared
from . import legal_source_family_bridge as bridge
from ..backends import process
from ..formalization.autoencoder import native_family_lean_emitters as emitters

SCHEMA = "legal-source-family-lake/v1"
MAX_ROWS = shared.MAX_ROWS
MAX_PROJECT_BYTES = 8 * 1024**2
_json, _sha = shared._json, shared._sha
_LAKEFILE = ('name = "legal_source_family"\nversion = "0.1.0"\n\n'
             '[[lean_lib]]\nname = "legal"\nroots = ["LegalSourceFamily"]\n')
_SCOPE = {
    "admitted": False, "formalized": False, "source_semantics_verified": False,
    "proof_authority": False, "all_logic_families_supported": False,
    "cross_family_equivalence_verified": False,
    "scope": "Compilation of exactly regenerated declared family interpretations and source occurrences; no source-meaning or norm-truth assertion.",
}


def _pins():
    return bridge.producer_pins() | {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in (shared, bridge, process, emitters)
    } | {str(Path(__file__).resolve()): _sha(Path(__file__).read_bytes())}


_IMPORTED_PINS = _pins()


@dataclass(frozen=True)
class SourceFamilyPreparation:
    manifest_json: str
    input_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        return json.loads(self.manifest_json)


@dataclass(frozen=True)
class SourceFamilyReceipt:
    receipt_json: str

    def to_dict(self):
        return json.loads(self.receipt_json)


def _inputs(requests):
    if type(requests) not in (list, tuple) or not 0 < len(requests) <= MAX_ROWS:
        raise ValueError(f"requests must contain 1..{MAX_ROWS} entries")
    identities = set()
    for entry in requests:
        if type(entry) is not dict or set(entry) != {
                "candidate", "interpretation", "occurrence_bindings", "family"}:
            raise ValueError("exact original bridge request fields required")
        candidate = entry["candidate"]
        if type(candidate) is not dict or set(candidate) != {
                "candidate_id", "source_text", "source_sha256", "canonical_ir"}:
            raise ValueError("exact candidate fields required")
        shared._bounded_rows([candidate])
        if type(entry["family"]) is not str or not entry["family"] or len(entry["family"]) > 128:
            raise ValueError("bounded family name required")
        identity = (candidate["candidate_id"], entry["family"])
        if identity in identities:
            raise ValueError("duplicate candidate/family request")
        identities.add(identity)
    try:
        raw = _json(requests)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("bounded finite JSON requests required") from error
    if len(raw.encode("utf-8")) > shared.MAX_INPUT_BYTES:
        raise ValueError("bridge request batch exceeds byte bound")
    return json.loads(raw)


def prepare_source_family_legal(requests, *, toolchain):
    """Regenerate each family adapter; unsupported entries block the whole batch."""
    if type(toolchain) is not str or not shared._TOOLCHAIN.fullmatch(toolchain):
        raise ValueError("explicit version-pinned Lean toolchain required")
    if _pins() != _IMPORTED_PINS:
        raise ValueError("source family gate producer changed since import")
    inputs = _inputs(requests)
    files = {
        "lakefile.toml": _LAKEFILE, "lean-toolchain": toolchain + "\n",
        "LegalSourceFamily/Prelude.lean": "namespace LegalSourceFamily\n" + emitters.PRELUDE + "\nend LegalSourceFamily\n",
    }
    candidates, imports = [], []
    for index, entry in enumerate(inputs):
        candidate = entry["candidate"]
        record = {
            "candidate_id": candidate["candidate_id"], "family": entry["family"],
            "source_sha256": candidate["source_sha256"],
            "canonical_ir_sha256": _sha(_json(candidate["canonical_ir"])),
            "interpretation_sha256": _sha(_json(entry["interpretation"])),
            "occurrence_bindings_sha256": _sha(_json(entry["occurrence_bindings"])),
            "request_sha256": _sha(_json(entry)), "status": "unsupported", "module": None,
        }
        try:
            result = bridge.prepare_source_family(candidate, entry["interpretation"],
                entry["occurrence_bindings"], family=entry["family"])
            bridge.validate_source_family(result, **entry)
            body = result["lean_body"]
            if type(body) is not str or not body.strip() or shared._REFUSED.search(body):
                raise ValueError("refused Lean keyword or placeholder in emitted source")
            module = f"LegalSourceFamily.Candidate{index:04d}"
            content = f"import LegalSourceFamily.Prelude\nnamespace {module}\n{body}\nend {module}\n"
            files[module.replace(".", "/") + ".lean"] = content
            imports.append("import " + module)
            record.update(status="supported", module=module, lean_sha256=_sha(content),
                bridge_sha256=_sha(_json(result)), profile=result["profile"],
                canonical_rule_count=len(candidate["canonical_ir"]["rules"]),
                source_occurrence_count=len(entry["occurrence_bindings"]),
                declared_adapter_regeneration_verified=True)
        except (ValueError, TypeError, KeyError) as error:
            record["reason"] = str(error)
        candidates.append(record)
    supported = all(row["status"] == "supported" for row in candidates)
    if supported:
        files["LegalSourceFamily.lean"] = "\n".join(imports) + "\n"
    else:
        files = {}
    raw = _json(inputs)
    files["source-family-inputs.json"] = raw + "\n"
    if sum(len(body.encode("utf-8")) for body in files.values()) > MAX_PROJECT_BYTES:
        raise ValueError("regenerated project exceeds byte bound")
    manifest = {
        "schema": SCHEMA, "toolchain": toolchain, "target": "legal",
        "status": "prepared" if supported else "blocked", "backend_executed": False,
        "all_candidates_supported": supported, "candidates": candidates,
        "input_sha256": _sha(raw), "producer_pins": dict(_IMPORTED_PINS),
        "file_sha256": {name: _sha(body) for name, body in sorted(files.items())}, **_SCOPE,
    }
    return SourceFamilyPreparation(_json(manifest), raw, tuple(sorted(files.items())))


def validate_preparation(preparation):
    if type(preparation) is not SourceFamilyPreparation:
        raise ValueError("SourceFamilyPreparation required")
    expected = prepare_source_family_legal(json.loads(preparation.input_json),
        toolchain=preparation.to_dict()["toolchain"])
    if expected != preparation:
        raise ValueError("candidate, interpretation, occurrence, emitted source or import coverage changed")


def build_source_family_legal(requests, *, toolchain, lake_executable,
                              timeout_seconds=60, output_directory=None):
    """Execute native lowercase target with pinned binaries in a fresh workspace."""
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be in (0, 60]")
    output = Path(output_directory).resolve() if output_directory is not None else None
    if output is not None and output.exists():
        raise ValueError("fresh output_directory required")
    preparation = prepare_source_family_legal(requests, toolchain=toolchain)
    validate_preparation(preparation)
    receipt = preparation.to_dict()
    receipt.update(build_passed=False, manifest_coverage_passed=False, compiled_modules=[],
        expected_modules=[], command=None, returncode=None)
    if receipt["all_candidates_supported"]:
        executable, binaries, probes = shared._installed_toolchain(lake_executable, toolchain)
        command = (str(executable), "build", "legal")
        modules = ["LegalSourceFamily.Prelude", *(row["module"] for row in receipt["candidates"]), "LegalSourceFamily"]
        paths = tuple(".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules)
        environment = {"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "2"}
        result = process.BoundedToolRunner().run(process.ToolRunRequest(
            argv=command, input_files=dict(preparation.files), output_paths=paths,
            environment=environment,
            limits=process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
                resident_memory_bytes=2 * 1024**3, max_output_bytes=262_144,
                max_input_bytes=MAX_PROJECT_BYTES, max_workspace_bytes=128 * 1024**2,
                max_output_files=MAX_ROWS + 2)))
        validate_preparation(preparation)
        binary_match = all(_sha(Path(name).read_bytes()) == digest for name, digest in binaries.items())
        artifacts = {name: _sha(raw) for name, raw in result.output_files.items()}
        coverage = set(artifacts) == set(paths) and all(result.output_files.values())
        passed = bool(result.ok and result.pid is not None and tuple(result.command) == command
            and not result.output_truncated and not result.workspace_limit_exceeded
            and coverage and binary_match and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
        receipt.update(status="passed" if passed else "failed", backend_executed=result.pid is not None,
            build_passed=passed, manifest_coverage_passed=bool(coverage), expected_modules=modules,
            compiled_modules=[name for name, path in zip(modules, paths) if path in artifacts],
            command=list(command), command_sha256=_sha(_json(list(command))), binary_sha256=binaries,
            binary_pins_match=binary_match, version_probe=probes, returncode=result.returncode,
            artifact_sha256=artifacts, stdout=result.stdout, stderr=result.stderr,
            stdout_sha256=_sha(result.stdout), stderr_sha256=_sha(result.stderr),
            timed_out=result.timed_out, output_truncated=result.output_truncated,
            workspace_limit_exceeded=result.workspace_limit_exceeded, resource_exhausted=result.resource_exhausted,
            unavailable=result.unavailable, cancelled=result.cancelled, workspace_cleaned=result.workspace_cleaned,
            process_tree_terminated=result.process_tree_terminated, error=result.error,
            execution_environment=environment,
            execution_limits={"timeout_seconds": timeout_seconds, "cpu_seconds": timeout_seconds,
                "sampled_tree_rss_bytes": 2 * 1024**3, "max_output_bytes": 262_144,
                "max_input_bytes": MAX_PROJECT_BYTES, "max_workspace_bytes": 128 * 1024**2})
    receipt["receipt_sha256"] = _sha(_json(receipt))
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
        files = dict(preparation.files) | {"source-family-manifest.json": preparation.manifest_json + "\n",
                                          "source-family-receipt.json": _json(receipt) + "\n"}
        for name, body in files.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(body)
    return SourceFamilyReceipt(_json(receipt))


__all__ = ["prepare_source_family_legal", "validate_preparation", "build_source_family_legal",
           "SourceFamilyPreparation", "SourceFamilyReceipt", "SCHEMA", "MAX_ROWS"]
