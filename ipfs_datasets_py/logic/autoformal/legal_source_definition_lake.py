"""Regenerate source-bound definition ASTs and compile exact lowercase legal."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from . import legal_source_definition_bridge as bridge
from . import legal_pilot_lake as shared
from ..backends import process
from ..formalization.autoencoder import native_family_lean_emitters as emitters

SCHEMA = "legal-source-definition-lake/v1"
LIMIT = 8 * 1024**2


def pins():
    return bridge.producer_pins() | {str(Path(module.__file__).resolve()): shared._sha(Path(module.__file__).read_bytes())
        for module in (shared, process, emitters)} | {str(Path(__file__).resolve()): shared._sha(Path(__file__).read_bytes())}


_PINS = pins()


@dataclass(frozen=True)
class Preparation:
    inputs: str
    manifest: str
    files: tuple

    def to_dict(self):
        return json.loads(self.manifest)


def prepare(requests, *, toolchain):
    bridge.require(pins() == _PINS, "definition gate implementation changed")
    bridge.require(type(requests) is list and 1 <= len(requests) <= 64, "one to64 definition requests required")
    bridge.require(type(toolchain) is str and shared._TOOLCHAIN.fullmatch(toolchain), "version-pinned Lean toolchain required")
    raw = shared._json(requests)
    bridge.require(len(raw.encode()) <= LIMIT, "bounded definition batch required")
    inputs = json.loads(raw)
    files = {"lakefile.toml": 'name = "legal_definition"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalDefinition"]\n',
             "lean-toolchain": toolchain + "\n",
             "LegalDefinition/Prelude.lean": "namespace LegalDefinition\n" + emitters.PRELUDE + "\nend LegalDefinition\n",
             "definition-inputs.json": raw + "\n"}
    identities, records, imports = set(), [], []
    for index, request in enumerate(inputs):
        report = bridge.prepare_definition(request)
        bridge.validate_definition(report, request)
        identity = (report["declaration_id"], report["family"])
        bridge.require(identity not in identities, "duplicate definition identity/family")
        identities.add(identity)
        body = report["lean_body"]
        bridge.require(body.strip() and not shared._REFUSED.search(body), "forbidden generated Lean keyword")
        module = f"LegalDefinition.Definition{index:04d}"
        files[module.replace(".", "/") + ".lean"] = f"import LegalDefinition.Prelude\nnamespace {module}\n{body}\nend {module}\n"
        imports.append("import " + module)
        records.append({"declaration_id": identity[0], "family": identity[1], "module": module,
                        "request_sha256": bridge.digest(request), "bridge_sha256": bridge.digest(report),
                        "native_ast_sha256": bridge.digest(report["native_ast"]), "document_id": report["document_id"]})
    files["LegalDefinition.lean"] = "\n".join(imports) + "\n"
    bridge.require(sum(len(s.encode()) for s in files.values()) <= LIMIT, "project byte bound exceeded")
    manifest = {"schema": SCHEMA, "target": "legal", "toolchain": toolchain, "definitions": records,
                "input_sha256": shared._sha(raw), "file_sha256": {n: shared._sha(s) for n, s in files.items()},
                "producer_pins": _PINS, "source_semantics_verified": False, "admitted": False,
                "training_qualified": False, "proof_authority": False}
    return Preparation(raw, shared._json(manifest), tuple(sorted(files.items())))


def validate(preparation):
    bridge.require(type(preparation) is Preparation, "typed definition preparation required")
    expected = prepare(json.loads(preparation.inputs), toolchain=preparation.to_dict()["toolchain"])
    bridge.require(expected == preparation, "definition input, scope, AST, module coverage or emitted source changed")


def build(requests, *, toolchain, lake_executable, output_directory, timeout_seconds=60):
    bridge.require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 60, "bounded compiler timeout required")
    output = Path(output_directory).resolve()
    bridge.require(not output.exists(), "fresh build output directory required")
    preparation = prepare(requests, toolchain=toolchain)
    validate(preparation)
    executable, binaries, probes = shared._installed_toolchain(lake_executable, toolchain)
    command = (str(executable), "build", "legal")
    manifest = preparation.to_dict()
    modules = ["LegalDefinition.Prelude", *(r["module"] for r in manifest["definitions"]), "LegalDefinition"]
    paths = tuple(".lake/build/lib/lean/" + m.replace(".", "/") + ".olean" for m in modules)
    result = process.BoundedToolRunner().run(process.ToolRunRequest(argv=command,
        input_files=dict(preparation.files), output_paths=paths,
        environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "2"},
        limits=process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=262144, max_input_bytes=LIMIT,
            max_workspace_bytes=128 * 1024**2, max_output_files=66)))
    validate(preparation)
    unchanged = all(shared._sha(Path(name).read_bytes()) == digest for name, digest in binaries.items())
    coverage = set(result.output_files) == set(paths) and all(result.output_files.values())
    passed = bool(result.ok and result.pid is not None and tuple(result.command) == command and coverage and unchanged
                  and not result.output_truncated and not result.workspace_limit_exceeded
                  and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
    receipt = manifest | {"build_passed": passed, "backend_executed": result.pid is not None,
        "expected_modules": modules, "compiled_modules": [m for m, p in zip(modules, paths) if p in result.output_files],
        "manifest_coverage_passed": bool(coverage), "command": list(command), "returncode": result.returncode,
        "binary_sha256": binaries, "binaries_unchanged": unchanged, "version_probes": probes,
        "artifact_sha256": {p: shared._sha(raw) for p, raw in result.output_files.items()},
        "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out,
        "output_truncated": result.output_truncated, "workspace_limit_exceeded": result.workspace_limit_exceeded,
        "workspace_cleaned": result.workspace_cleaned, "process_tree_terminated": result.process_tree_terminated,
        "scope": "Native compilation of caller-declared section-local unary category definitions; no automatic legal interpretation."}
    receipt["receipt_sha256"] = shared._sha(shared._json(receipt))
    output.mkdir(parents=True, exist_ok=False)
    for name, body in preparation.files:
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    (output / "receipt.json").write_text(shared._json(receipt) + "\n")
    return receipt
