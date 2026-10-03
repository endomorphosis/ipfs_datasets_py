"""Actual bounded Lake checks of validated decoder records and their shapes.

The generated Lean structures describe this exact artifact's field types and
presence, not every value of the domain schema. Native validators remain the
semantic owners. A successful build checks the represented instance against
those structural types; it neither proves source meaning nor qualifies eight
logic families. No caller-provided Lean, executable path, or success receipt is
accepted. Persisted observations require a fresh execution to regain trust.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import re
import struct
import sys
import types
import weakref

from . import native_formal_decoder as native
from ...logic.legal_ir import canonical_contracts as legal
from ...logic.backends import process
from ...logic.autoformal import tree_pin

SCHEMA = "autoencoder-schema-lake-artifact/v1"
RECEIPT_SCHEMA = "autoencoder-schema-lake-execution/v1"
TOOLCHAIN = "leanprover/lean4:v4.26.0"
LIBRARY = "DecoderSchema"
MAX_INPUT_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 256 * 1024
DESCRIPTOR_FIELDS = frozenset({"logic_family", "profile", "properties", "view_role",
                               "representation_kind", "producer_id"})
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "proof_authority": False, "source_semantics_verified": False,
         "full_family_coverage_verified": False, "domain_wide_schema_verified": False,
         "checkpoint_source_tie_verified": False, "promotion_performed": False}
_issued = weakref.WeakSet()
_imported_sources = {}


class SchemaLakeError(ValueError):
    """Malformed, unsupported, stale or unverified decoder artifact."""


def _require(value, reason):
    if not value:
        raise SchemaLakeError(reason)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise SchemaLakeError("finite bounded JSON required") from exc


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _workspace():
    # The staged emitter is deliberately inside this checkout. A different
    # imported editable tree cannot nominate itself as the selected workspace.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() and (parent / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file():
            return parent
    raise SchemaLakeError("canonical workspace checkout is unavailable")


def _owned_code(module):
    """Loaded function/method identities, excluding generated dataclass code."""
    path = Path(module.__file__).resolve()
    result = {}
    def add(name, value):
        if isinstance(value, (staticmethod, classmethod)):
            value = value.__func__
        try:
            value = inspect.unwrap(value)
        except ValueError:
            return
        code = getattr(value, "__code__", None)
        if isinstance(code, types.CodeType) and Path(code.co_filename).resolve() == path:
            result[name] = code
    for name, value in vars(module).items():
        add(name, value)
        if isinstance(value, type) and value.__module__ == module.__name__:
            for member, method in vars(value).items():
                add(name + "." + member, method.fget if isinstance(method, property) else method)
    return result


def _pin_imported_module(module):
    """Capture first-use identity and reject later disk or loaded-code drift.

    On first observation, owned function code must also match compilation of
    current source bytes. This detects a dependency imported before its file
    was edited, instead of merely blessing the new on-disk digest. Generated
    methods and arbitrary external dependencies are outside this limited pin.
    """
    path = Path(module.__file__).resolve()
    _require(_workspace() in path.parents and path.is_file(), "imported producer resolved outside canonical workspace")
    raw = path.read_bytes()
    owned = _owned_code(module)
    # Code objects compare structural content; marshal bytes also encode
    # incidental string interning/reference layout and are not stable here.
    identity = {"path": str(path), "sha256": _sha(raw), "owned_code": owned}
    existing = _imported_sources.get(module.__name__)
    if existing is not None:
        _require(identity == existing, "imported producer source or executed code changed: " + module.__name__)
        return identity["sha256"]
    compiled = compile(raw, str(path), "exec", dont_inherit=True)
    candidates = set()
    def visit(code):
        candidates.add(code)
        for child in code.co_consts:
            if isinstance(child, types.CodeType):
                visit(child)
    visit(compiled)
    _require(all(value in candidates for value in owned.values()),
             "loaded producer code differs from current source: " + module.__name__)
    _imported_sources[module.__name__] = identity
    return identity["sha256"]


def _pin_workspace():
    _require(Path(tree_pin.workspace_root()).resolve() == _workspace(), "tree pin resolved outside canonical workspace")
    for module in (sys.modules[__name__], process, native, legal, tree_pin):
        _pin_imported_module(module)
    resolved = tree_pin.require_workspace_logic_tree()
    for name in ("ipfs_datasets_py.logic.legal_ir.canonical_compiler",
                 "ipfs_datasets_py.logic.legal_ir.canonical_decompiler",
                 "ipfs_datasets_py.logic.deontic.utils.deontic_parser"):
        _pin_imported_module(importlib.import_module(name))
    return resolved


def _validate_tree(value, *, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    _require(count[0] <= 8192 and depth <= 24, "artifact tree bound exceeded")
    if type(value) is dict:
        _require(len(value) <= 128 and all(type(key) is str and 0 < len(key) <= 128 for key in value),
                 "bounded string-keyed record required")
        for key, child in value.items():
            _require(not any(0xD800 <= ord(c) <= 0xDFFF for c in key), "invalid Unicode field name")
            _validate_tree(child, depth=depth + 1, count=count)
    elif type(value) is list:
        _require(len(value) <= 256, "artifact array bound exceeded")
        for child in value:
            _validate_tree(child, depth=depth + 1, count=count)
    elif type(value) is str:
        _require(len(value) <= 16384 and not any(0xD800 <= ord(c) <= 0xDFFF for c in value),
                 "bounded Unicode string required")
    elif type(value) is int:
        _require(abs(value) < 2 ** 256, "integer representation bound exceeded")
    elif type(value) is float:
        _require(math.isfinite(value), "nonfinite numeric value")
    else:
        _require(value is None or type(value) is bool, "unsupported artifact value type")


def _sources(domain):
    pinned = _pin_workspace()
    root = Path(native.__file__).resolve().parents[2]
    rows = {"schema_emitter": _hash_file(Path(__file__)),
            "logic/backends/process.py": _hash_file(Path(process.__file__))}
    if domain == "legal_ir":
        rows["logic/legal_ir/canonical_contracts.py"] = _hash_file(Path(legal.__file__))
    else:
        rows["optimizers/logic_theorem_optimizer/native_formal_decoder.py"] = _hash_file(Path(native.__file__))
        dependencies = native._validator_sources(domain, space_schema="native-projection-feature-space/v1")
        for relative in dependencies:
            module_name = "ipfs_datasets_py." + relative.removesuffix(".py").replace("/", ".")
            dependencies[relative] = _pin_imported_module(importlib.import_module(module_name))
        rows.update(dependencies)
    rows.update({"canonical_pin:" + role: _hash_file(Path(path)) for role, path in pinned.items()})
    _require(root.is_dir(), "selected producer package is unavailable")
    return {"scope": "listed_emitter_validator_sources_and_owned_function_code_not_full_transitive_provenance",
            "files": rows, "sha256": _sha(_raw(rows))}


def _validate_output(domain, output):
    _require(type(output) is dict, "closed decoded output mapping required")
    if domain == "legal_ir":
        _require(set(output) == {"rules"} and type(output["rules"]) is list
                 and 1 <= len(output["rules"]) <= 64, "nonempty bounded canonical rules required")
        try:
            restored = legal.CanonicalRoundTripIR.from_dict(output).to_dict()
        except (ValueError, TypeError) as exc:
            raise SchemaLakeError("canonical rule validation failed") from exc
        _require(_raw(restored) == _raw(output), "canonical validation must not normalize the input")
        return {"validator": "CanonicalRoundTripIR@1", "projection_id": "canonical-deontic-rules/v1",
                "logic_family": "deontic", "schema": legal.CANONICAL_ROUNDTRIP_IR_SCHEMA_VERSION}
    _require(set(output) == {"projection_id", "expression", *DESCRIPTOR_FIELDS},
             "native output must contain exactly projection ID, descriptor fields and expression")
    descriptor = {key: output[key] for key in DESCRIPTOR_FIELDS}
    _require(type(output["projection_id"]) is str and type(descriptor["logic_family"]) is str,
             "native projection and family names required")
    try:
        # Security's older readout validates family/profile; close the remaining
        # metadata here against the existing target producer's exact contract.
        if domain == "security_ir":
            from ...logic.security_ir.code_logic_projection import describe_code_logic_projection_profile
            routes = {row["payload_schema"]: row for row in describe_code_logic_projection_profile()["projections"]}
            route = routes.get(output["projection_id"])
            _require(route is not None, "unsupported Security native projection")
            _require(descriptor == {"logic_family": route["family"], "profile": route["profile"] or None,
                "properties": [], "view_role": route["view_role"] or None,
                "representation_kind": "native_typed_document", "producer_id": "security-code-logic-projection"},
                "Security native descriptor differs from exact registered route")
        checked = native._validate_expression(domain, output["projection_id"], descriptor, output["expression"])
    except (ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, SchemaLakeError):
            raise
        raise SchemaLakeError("unsupported or invalid native output: " + str(exc)) from exc
    return {"validator": checked["validator"], "projection_id": output["projection_id"],
            "logic_family": descriptor["logic_family"], "validation_scope": checked["validation_scope"],
            "descriptor_sha256": _sha(_raw(descriptor))}


def _string(value):
    # Numeric Unicode scalar constructors avoid Lean quotation/injection issues
    # for arbitrary source strings, including newlines and quotes.
    return "(String.ofList [" + ", ".join("Char.ofNat " + str(ord(c)) for c in value) + "])"


class _Renderer:
    def __init__(self):
        self.declarations = ["inductive AbsentValue where | null",
                             "inductive EmptyElement where",
                             "structure ExactFloat64 where\n  bits : UInt64",
                             "inductive LegalModality where | obligation | permission | prohibition"]
        self.shapes = {}
        self.schemas = []

    def render(self, value, path=(), *, legal_mode=False):
        if legal_mode and len(path) == 3 and path[0] == "rules" and path[-1] == "modality":
            return "LegalModality", "LegalModality." + {"O": "obligation", "P": "permission", "F": "prohibition"}[value]
        if legal_mode and len(path) == 3 and path[0] == "rules" and path[-1] in {"conditions", "exceptions", "temporal"}:
            # The canonical seven-facet schema already fixes these element
            # types; an empty qualifier list does not narrow them to Empty.
            return "List String", "[" + ", ".join(_string(item) for item in value) + "]"
        if value is None:
            return "AbsentValue", "AbsentValue.null"
        if type(value) is bool:
            return "Bool", "true" if value else "false"
        if type(value) is int:
            return "Int", "(" + str(value) + " : Int)"
        if type(value) is float:
            bits = struct.unpack(">Q", struct.pack(">d", value))[0]
            return "ExactFloat64", "(ExactFloat64.mk " + str(bits) + ")"
        if type(value) is str:
            return "String", _string(value)
        if type(value) is list:
            children = [self.render(child, path + (index,), legal_mode=legal_mode) for index, child in enumerate(value)]
            types = sorted({kind for kind, _ in children})
            if not types:
                return "List EmptyElement", "([] : List EmptyElement)"
            if len(types) == 1:
                return "List (" + types[0] + ")", "[" + ", ".join(text for _, text in children) + "]"
            key = ("sum", tuple(types))
            name = self.shapes.get(key)
            if name is None:
                name = "Choice" + str(len(self.schemas))
                self.shapes[key] = name
                self.declarations.append("inductive " + name + " where\n" + "\n".join(
                    "  | option" + str(i) + " : " + kind + " → " + name for i, kind in enumerate(types)))
                self.schemas.append({"lean_type": name, "kind": "tagged_union", "alternatives": types})
            return "List " + name, "[" + ", ".join("(" + name + ".option" + str(types.index(kind)) + " " + text + ")" for kind, text in children) + "]"
        children = [(key, *self.render(child, path + (key,), legal_mode=legal_mode)) for key, child in sorted(value.items())]
        key = ("record", tuple((key, kind) for key, kind, _ in children))
        name = self.shapes.get(key)
        if name is None:
            name = "Record" + str(len(self.schemas))
            self.shapes[key] = name
            fields = [{"source_field": field, "lean_field": "field" + str(i), "lean_type": kind}
                      for i, (field, kind, _) in enumerate(children)]
            self.declarations.append("structure " + name + " where" + ("\n" if fields else "") +
                "\n".join("  " + field["lean_field"] + " : " + field["lean_type"] for field in fields))
            self.schemas.append({"lean_type": name, "kind": "closed_record", "fields": fields,
                                 "missing_fields": "not_materialized_or_defaulted"})
        if not children:
            return name, name + ".mk"
        return name, "({ " + ", ".join("field" + str(i) + " := " + text for i, (_, _, text) in enumerate(children)) + " } : " + name + ")"


def build_schema_artifact(domain, output, *, source_text, checkpoint_sha256):
    """Regenerate typed Lean for one exact validated output; run no backend."""
    _require(type(domain) is str and domain in {"legal_ir", "security_ir", "intent_ir", "ui_ux_ir"}, "unsupported domain")
    _require(type(source_text) is str and 0 < len(source_text.encode("utf-8")) <= MAX_INPUT_BYTES,
             "nonempty bounded exact source text required")
    _require(type(checkpoint_sha256) is str and re.fullmatch("[0-9a-f]{64}", checkpoint_sha256),
             "explicit checkpoint digest required; paths are not accepted")
    _validate_tree(output)
    raw = _raw(output)
    _require(len(raw) <= MAX_INPUT_BYTES, "decoded output exceeds byte bound")
    source_identity = _sources(domain)
    observation = _validate_output(domain, output)
    renderer = _Renderer()
    kind, instance = renderer.render(output, legal_mode=domain == "legal_ir")
    source = "namespace DecoderSchema\n\n" + "\n\n".join(renderer.declarations)
    source += "\n\ndef decodedInstance : " + kind + " :=\n  " + instance + "\n\nend DecoderSchema\n"
    _require(len(source.encode()) <= MAX_SOURCE_BYTES, "generated Lean exceeds source bound")
    shape = {"schema": "decoder-artifact-structural-shape/v1", "root_type": kind,
             "records_and_unions": renderer.schemas,
             "scalar_encoding": {"string": "unicode_scalar_list", "integer": "Int", "boolean": "Bool",
                                 "float": "exact_ieee754_binary64_bits", "null": "AbsentValue.null"},
             "array_policy": "preserve_order_and_multiplicity_empty_arrays_have_uninhabited_element_type"}
    _require(_sources(domain) == source_identity, "producer sources changed during generation")
    result = {"schema": SCHEMA, "domain": domain, "scope": "exact_artifact_structural_shape_and_instance",
        "input_sha256": _sha(raw), "source_sha256": _sha(source_text.encode()),
        "source_binding_scope": "provided_exact_text_bytes_not_native_source_digest_or_semantic_fidelity",
        "checkpoint_sha256": checkpoint_sha256, "checkpoint_binding_scope": "caller_supplied_digest_not_loaded_or_verified",
        "native_validation": observation, "shape": shape, "shape_sha256": _sha(_raw(shape)),
        "lean_source": source, "lean_source_sha256": _sha(source.encode()),
        "producer_sources": source_identity, **FALSE}
    result["artifact_sha256"] = _sha(_raw(result))
    _require(len(_raw(result)) <= MAX_ARTIFACT_BYTES, "generated artifact exceeds byte bound")
    return result


@dataclass(frozen=True, eq=False)
class SchemaLakeExecution:
    """Immutable execution observation; detached JSON cannot restore trust."""
    _bytes: bytes

    def to_dict(self):
        return json.loads(self._bytes)


def _write(path, data):
    with path.open("xb") as handle:
        handle.write(data)


def validate_schema_output(domain, output, *, source_text, checkpoint_sha256,
                           output_directory, timeout_seconds=60):
    """Run only regenerated Lean with the installed Lake; retain exact inputs/log."""
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
             and 1 <= timeout_seconds <= 120, "bounded Lake timeout between 1 and 120 seconds required")
    artifact = build_schema_artifact(domain, output, source_text=source_text, checkpoint_sha256=checkpoint_sha256)
    directory = Path(output_directory).absolute()
    _require(not directory.exists() and directory.parent.is_dir(), "fresh output directory with existing parent required")
    binary = Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin/lake"
    lean = binary.with_name("lean")
    _require(binary.is_file() and lean.is_file(), "installed Lean4.26.0 Lake missing; downloads forbidden")
    toolchain = {"identifier": TOOLCHAIN, "lake": str(binary), "lake_sha256": _hash_file(binary),
                 "lean": str(lean), "lean_sha256": _hash_file(lean)}
    files = {"lean-toolchain": TOOLCHAIN + "\n",
        "lakefile.lean": "import Lake\nopen Lake DSL\npackage decoderSchema\nlean_lib DecoderSchema\n",
        "DecoderSchema.lean": artifact["lean_source"]}
    project_sha = _sha(_raw(files))
    directory.mkdir(mode=0o700)
    for name, text in files.items():
        _write(directory / name, text.encode())
    _write(directory / "artifact.json", _raw(artifact))
    runner = process.BoundedToolRunner(workspace_root=directory / "build")
    version = runner.run(process.ToolRunRequest(argv=(str(binary), "--version"),
        limits=process.ToolRunLimits(timeout_seconds=min(5, timeout_seconds), max_output_bytes=16384)))
    _write(directory / "toolchain.log", (version.stdout + "\n" + version.stderr).encode())
    _require(version.ok and not version.output_truncated and "Lean version 4.26.0" in version.stdout,
             "installed Lake does not identify the required Lean4.26.0 toolchain")
    toolchain["version_output"] = version.stdout
    limits = process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
        max_output_bytes=MAX_LOG_BYTES, max_input_bytes=MAX_SOURCE_BYTES + 4096,
        max_workspace_bytes=64 * 1024 * 1024)
    built = runner.run(process.ToolRunRequest(argv=(str(binary), "build", LIBRARY),
        input_files=files, environment={"ELAN_TOOLCHAIN": TOOLCHAIN}, limits=limits))
    log = (built.stdout + "\n" + built.stderr).encode()
    _write(directory / "lake.log", log)
    unchanged = build_schema_artifact(domain, output, source_text=source_text, checkpoint_sha256=checkpoint_sha256) == artifact
    toolchain_unchanged = _hash_file(binary) == toolchain["lake_sha256"] and _hash_file(lean) == toolchain["lean_sha256"]
    clean = built.ok and not built.output_truncated and not built.workspace_limit_exceeded
    passed = clean and unchanged and toolchain_unchanged
    observation = {"schema": RECEIPT_SCHEMA, "domain": domain, "scope": artifact["scope"],
        "schema_instance_typecheck_passed": bool(passed), "backend_executed": True,
        "reason": "" if passed else "lake_failed_or_bound_exceeded_or_producer_changed",
        "artifact_sha256": artifact["artifact_sha256"], "input_sha256": artifact["input_sha256"],
        "shape_sha256": artifact["shape_sha256"], "source_sha256": artifact["source_sha256"],
        "checkpoint_sha256": checkpoint_sha256, "lean_source_sha256": artifact["lean_source_sha256"],
        "project_sha256": project_sha, "producer_sources": artifact["producer_sources"],
        "toolchain": toolchain, "command": [str(binary), "build", LIBRARY],
        "returncode": built.returncode, "elapsed_seconds": built.elapsed_seconds,
        "timed_out": built.timed_out, "output_truncated": built.output_truncated,
        "workspace_limit_exceeded": built.workspace_limit_exceeded,
        "directory": str(directory), "log_sha256": _sha(log), "log_bytes": len(log),
        "retained_files": {name: _sha((directory / name).read_bytes())
                           for name in (*files, "artifact.json", "lake.log", "toolchain.log")}, **FALSE}
    encoded = _raw(observation)
    _write(directory / "receipt.json", encoded)
    execution = SchemaLakeExecution(encoded)
    _issued.add(execution)
    return execution


def verify_schema_execution(execution, domain, output, *, source_text, checkpoint_sha256):
    """Verify an object from this process's actual execution; reject JSON claims.

    Archived JSON is audit material only. Re-run validate_schema_output to
    establish fresh execution evidence after process restart or source changes.
    """
    _require(type(execution) is SchemaLakeExecution and execution in _issued,
             "actual in-process Lake execution required; serialized or constructed claims are not evidence")
    receipt = execution.to_dict()
    artifact = build_schema_artifact(domain, output, source_text=source_text, checkpoint_sha256=checkpoint_sha256)
    _require(receipt["artifact_sha256"] == artifact["artifact_sha256"], "execution belongs to a different artifact or producer")
    directory = Path(receipt["directory"])
    for name, digest in receipt["retained_files"].items():
        path = directory / name
        _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_ARTIFACT_BYTES,
                 "retained execution file missing or invalid")
        _require(_hash_file(path) == digest, "retained execution file changed")
    receipt_path = directory / "receipt.json"
    _require(receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.stat().st_size <= MAX_ARTIFACT_BYTES
             and receipt_path.read_bytes() == execution._bytes,
             "immutable execution receipt changed")
    for name in ("lake", "lean"):
        path = Path(receipt["toolchain"][name])
        _require(path.is_file() and _hash_file(path) == receipt["toolchain"][name + "_sha256"], "installed toolchain changed")
    return receipt


__all__ = ["SchemaLakeError", "SchemaLakeExecution", "build_schema_artifact",
           "validate_schema_output", "verify_schema_execution"]

# Freeze already imported core producers before this module becomes callable.
for _module in (sys.modules[__name__], process, native, legal, tree_pin):
    _pin_imported_module(_module)
