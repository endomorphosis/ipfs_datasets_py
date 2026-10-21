"""Shared source-bound definitions and conditional native Lean composition.

This bounded orchestration delegates native parsing and lowering. Identical
explicit definition interpretations may share a module only with identical
scope, source and physical origins. Kernel checking does not establish law.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import legal_corpus_definition_use_lake_v2 as parent_owner
from . import legal_corpus_lake as joint_owner

SCHEMA = "legal-corpus-shared-definition-lake-preparation/v1"
KEY_SCHEMA = "legal-corpus-exact-definition-sharing-key/v1"
BUILD_SCHEMA = "legal-corpus-shared-definition-native-build/v1"
PROFILE = "exact-source-scoped-unary-definition-sharing/v1"
MAX_FILES = 2 * joint_owner.MAX_CANDIDATES + 5
FALSE_FLAGS = dict(joint_owner.FALSE_FLAGS)
FIELDS = {
    "profile", "toolchain", "population", "population_cid", "original_preparation_cid",
    "definition_modules", "norm_bindings", "expected_modules", "file_sha256",
    "producer_pins", "native_producer_pins", "shared_definition_deduplication",
    "external_definition_resolution", "preparation_only", "theorem_assumptions", *FALSE_FLAGS,
}

# Parent components are donor/consumer/alias/joint projects, not legacy norms.
PARENT_SCHEMA = "legal-corpus-parent-shared-definition-use-preparation/v1"
PARENT_PROFILE = "exact-parent-definition-use-module-sharing/v1"
PARENT_REPLAY_SCHEMA = "legal-corpus-parent-shared-replay-inputs/v1"
PARENT_REPLAY_PROFILE = "historical-parent-shared-public-replay-inputs/v1"
PARENT_REPLAY_FIELDS = {
    "schema", "profile", "manifest_sha256", "input_commitment_sha256", "inputs",
}
PARENT_REPLAY_INPUT_FIELDS = ("component_inputs", "expected_population", "toolchain")
MAX_PARENT_COMPONENTS = 8
MAX_PARENT_FILES = 6 * MAX_PARENT_COMPONENTS + 4
PARENT_FALSE_FLAGS = dict(parent_owner.PARENT_FALSE_FLAGS)
PARENT_FIELDS = {
    "profile", "toolchain", "population", "input_commitment_sha256", "components",
    "definition_modules", "module_bindings", "expected_modules", "module_imports",
    "file_sha256", "producer_pins", "native_producer_pins", "preparation_only",
    "lean_compilation_status", "proof_status", "theorem_assumptions",
    "child_file_policy", *PARENT_FALSE_FLAGS,
}


@dataclass(frozen=True)
class ParentSharedCorpusPreparation:
    """A bounded parent shared project; preparation confers no build authority."""

    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        raw = self.manifest_json.encode("utf-8")
        return contracts.load_record_bytes(raw, expected_sha256=_sha(raw))


@dataclass(frozen=True)
class SharedCorpusPreparation:
    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        raw = self.manifest_json.encode("utf-8")
        return contracts.load_record_bytes(raw, expected_sha256=_sha(raw))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fail(message):
    raise contracts.CorpusContractError(message)


def _pins():
    return joint_owner._pins() | {str(Path(joint_owner.__file__).resolve()):
        _sha(Path(joint_owner.__file__).read_bytes()), str(Path(__file__).resolve()):
        _sha(Path(__file__).read_bytes())}


def _sharing_key(candidate):
    bindings = [row for row in candidate["source_bindings"]
                if row["role"].startswith("definition_") or row["role"] == "scope_literal"]
    touched = {index for row in bindings for index in row["paragraph_indices"]}
    bindings += [row for row in candidate["source_bindings"] if row["role"].startswith("physical_paragraph/")
                 and touched.intersection(row["paragraph_indices"])]
    origins = {row["source_occurrence_cid"] for row in bindings}
    return contracts.seal_record({
        "schema": KEY_SCHEMA, "profile": PROFILE,
        "source_version_cid": candidate["source_version"]["record_cid"],
        "scope_record_cid": candidate["scope_record"]["record_cid"],
        "declaration": candidate["definition_record"]["declaration"],
        "native_ast": candidate["definition_record"]["native_ast"],
        "definition_symbol_rebinding": candidate["symbol_record"]["definition_symbol_rebinding"],
        "source_bindings": bindings,
        "source_occurrences": [row for row in candidate["source_occurrences"]
                               if row["record_cid"] in origins],
    })


def _parent_shared_offered(preparation):
    if type(preparation) is not ParentSharedCorpusPreparation:
        _fail("typed parent shared corpus preparation required")
    text, files = preparation.manifest_json, preparation.files
    if (type(text) is not str or len(text) > contracts.MAX_RECORD_BYTES
            or type(files) is not tuple or not 1 <= len(files) <= MAX_PARENT_FILES):
        _fail("bounded closed parent shared preparation required")
    pairs = []
    for pair in files:
        if (type(pair) is not tuple or len(pair) != 2
                or any(type(value) is not str for value in pair)):
            _fail("plain parent shared preparation file pairs required")
        pairs.append(list(pair))
    return {"manifest_json": text, "files": pairs}


def _parent_shared_capture(original, offered):
    inputs, population = original["component_inputs"], original["expected_population"]
    if (type(inputs) is not list or not 1 <= len(inputs) <= MAX_PARENT_COMPONENTS
            or type(population) is not list or len(population) != len(inputs)):
        _fail("closed ordered parent shared component population required")
    for item, pin in zip(inputs, population, strict=True):
        if (type(item) is not dict or len(item) != 3
                or any(type(key) is not str for key in item) or set(item) != {
                "assessment_raw", "expected_assessment_file_sha256", "review_inputs"}
                or type(pin) is not dict or len(pin) != 2
                or any(type(key) is not str for key in pin) or set(pin) != {
                    "component_cid", "assessment_file_sha256"}):
            _fail("closed parent shared input and independent population pins required")
        if (type(item["assessment_raw"]) is not bytes
                or not 0 < len(item["assessment_raw"]) <= contracts.MAX_RECORD_BYTES):
            _fail("bounded immutable parent shared assessment bytes required")
    # One expanded budget covers the complete population and offered output,
    # including aliases repeated across children, before any full-body hash.
    graph = {**original, "offered": None if offered is None else _parent_shared_offered(offered)}
    copied = parent_owner._ParentInputBudget().copy(graph)
    frozen = parent_owner._parent_commitment(copied)
    base = {key: value for key, value in copied.items() if key != "offered"}
    commitment = parent_owner._parent_commitment(base)
    if copied["offered"] is not None:
        candidate = copied["offered"]
        if (len(candidate["manifest_json"].encode()) > contracts.MAX_RECORD_BYTES
                or sum(len(body.encode()) for _, body in candidate["files"])
                > joint_owner.MAX_PROJECT_BYTES):
            _fail("offered parent shared project exceeds complete transport bounds")
    return copied, frozen, commitment


def _parent_shared_fence(original, copied, frozen, offered):
    if _parent_shared_capture(original, offered)[1] != frozen:
        _fail("caller parent shared inputs or offered preparation changed")
    snapshot = parent_owner._ParentInputBudget().copy(copied)
    if parent_owner._parent_commitment(snapshot) != frozen:
        _fail("detached parent shared inputs changed")


def _parent_shared_operation(original, operation, offered=None):
    copied, frozen, commitment = _parent_shared_capture(original, offered)
    failure = None
    try:
        result = operation(copied, commitment)
        _parent_shared_fence(original, copied, frozen, offered)
        # A later child or transport step may change an earlier child's backing
        # files without changing its Python input tree. Replay every original
        # physical source at the successful aggregate boundary as well.
        for item in copied["component_inputs"]:
            parent_owner.prepare_parent_definition_use_corpus_v1(
                **item, toolchain=copied["toolchain"])
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _parent_shared_fence(original, copied, frozen, offered)
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing parent shared input comparison also failed.")


def _parent_shared_pins():
    return parent_owner._pins(parent_owner._owners()) | {
        str(Path(__file__).resolve()): _sha(Path(__file__).read_bytes())}


def _parent_shared_check_inputs(copied):
    """Check closed public argument joins before any optional producer load."""
    toolchain = copied["toolchain"]
    if (type(toolchain) is not str or len(toolchain) > 128
            or not parent_owner._TOOLCHAIN.fullmatch(toolchain)):
        _fail("explicit pinned parent shared Lean toolchain required")
    # Population joins precede replay, so no missing/extra/reordered child can
    # be silently erased by module deduplication.
    for item, pin in zip(copied["component_inputs"], copied["expected_population"], strict=True):
        contracts.require_cid(pin["component_cid"], "expected parent component CID")
        contracts.require_sha256(pin["assessment_file_sha256"], "expected assessment file SHA256")
        review_inputs = item["review_inputs"]
        component_pin = review_inputs.get("expected_component_pin") if type(review_inputs) is dict else None
        if (item["expected_assessment_file_sha256"] != pin["assessment_file_sha256"]
                or type(component_pin) is not dict or component_pin.get("component_cid") != pin["component_cid"]):
            _fail("ordered parent shared population differs from original inputs")
        contracts.require_keys(review_inputs, parent_owner.REVIEW_INPUT_FIELDS,
                               "complete parent shared combined-review inputs")


def _parent_shared_prepare(copied, commitment):
    _parent_shared_check_inputs(copied)
    toolchain = copied["toolchain"]
    pins = _parent_shared_pins()
    namespace = "LegalCorpusParent"
    files = {
        "lakefile.toml": 'name = "legal_corpus_parent_shared_definition_use"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCorpusParent"]\n',
        "lean-toolchain": toolchain + "\n",
    }
    imports, fragments, definitions, components = {}, {}, {}, []
    native_pins = None
    for ordinal, (item, population) in enumerate(zip(
            copied["component_inputs"], copied["expected_population"], strict=True)):
        child = parent_owner.prepare_parent_definition_use_corpus_v1(**item, toolchain=toolchain)
        manifest, child_files = child.to_dict(), dict(child.files)
        if manifest["producer_pins"] != {key: value for key, value in pins.items()
                                         if key != str(Path(__file__).resolve())}:
            _fail("parent shared child producer closure differs")
        if native_pins is None:
            native_pins = manifest["native_producer_pins"]
        if native_pins != manifest["native_producer_pins"]:
            _fail("parent shared native producer closure differs")
        prelude = namespace + "/Prelude.lean"
        if prelude in files and files[prelude] != child_files[prelude]:
            _fail("parent shared Prelude differs")
        files[prelude] = child_files[prelude]
        imports[namespace + ".Prelude"] = []
        manifest_file = f"parent-component-{ordinal:04d}.json"
        binding_file = f"parent-input-bindings-{ordinal:04d}.json"
        files[manifest_file] = child.manifest_json
        files[binding_file] = child_files["parent-input-bindings.json"]
        mapping = {name: (None if name in ("lakefile.toml", namespace + ".lean")
                          else binding_file if name == "parent-input-bindings.json" else name)
                   for name in child_files}
        binding = manifest["review_intake_binding"]
        if (binding["component_pin"]["component_cid"] != population["component_cid"]
                or binding["assessment_file_sha256"] != population["assessment_file_sha256"]):
            _fail("replayed parent shared child differs from population pins")
        source_rows = {row["role"]: row for row in
                       manifest["review_source_binding"]["original_definitions"]}
        joint = None
        for fragment in manifest["native_fragments"]:
            role, module = fragment["role"], fragment["module"]
            path = module.replace(".", "/") + ".lean"
            body, dependencies = child_files[path], manifest["module_imports"][module]
            actual = re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", body)
            if actual != dependencies or parent_owner._REFUSED.search(body):
                _fail("parent shared child module imports or keywords differ")
            if role in ("donor", "consumer"):
                identity = {key: value for key, value in source_rows[role].items() if key != "role"}
            elif role == "alias":
                identity = {key: manifest["review_source_binding"][key]
                            for key in ("binding_record", "alias_record", "scope_binding")}
            else:
                identity = binding["component_pin"]
                joint = module
            fact = {"native": fragment["native"], "source_identity": identity,
                    "imports": dependencies, "body": body}
            if module in fragments and fragments[module]["fact"] != fact:
                _fail("conflicting parent shared module identity, imports or complete bytes")
            contributor = {"ordinal": ordinal, "role": role,
                           "component_cid": population["component_cid"]}
            if module not in fragments:
                fragments[module] = {"fact": fact, "contributors": []}
            fragments[module]["contributors"].append(contributor)
            files[path], imports[module] = body, dependencies
            if role in ("donor", "consumer"):
                if module not in definitions:
                    definitions[module] = {
                        "module": module, "module_path": path,
                        "module_sha256": _sha(body.encode()), "source_identity": identity,
                        "native_fragment": fragment["native"], "contributors": []}
                definitions[module]["contributors"].append(contributor)
        components.append({
            "ordinal": ordinal, **population, "original_preparation_cid": manifest["record_cid"],
            "manifest_file": manifest_file, "manifest_sha256": _sha(child.manifest_json.encode()),
            "input_bindings_file": binding_file,
            "input_bindings_sha256": _sha(files[binding_file].encode()),
            "original_file_mapping": mapping, "review_intake_binding": binding,
            "review_evidence": {
                "status": manifest["review_evidence_status"], "blockers": manifest["review_blockers"],
                "prerequisites_satisfied_under_selected_trust":
                    manifest["review_prerequisites_satisfied_under_selected_trust"]},
            "theorem_assumptions": manifest["theorem_assumptions"],
            "conditional_theorems": manifest["conditional_theorems"], "joint_module": joint,
        })
    imports[namespace] = sorted({row["joint_module"] for row in components})
    files[namespace + ".lean"] = "".join("import " + name + "\n" for name in imports[namespace])
    # Stable topological order of the exact union, without renaming fragments.
    ordered, remaining = [], set(imports)
    if any(dependency not in imports for values in imports.values() for dependency in values):
        _fail("parent shared import dependency escapes the closed population")
    while remaining:
        ready = sorted(name for name in remaining if set(imports[name]) <= set(ordered))
        if not ready:
            _fail("parent shared import dependency cycle")
        ordered.extend(ready)
        remaining.difference_update(ready)
    for module in ordered:
        body = files[module.replace(".", "/") + ".lean"]
        if (re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", body) != imports[module]
                or parent_owner._REFUSED.search(body)):
            _fail("parent shared complete module import/keyword contract differs")
    if (len(files) > MAX_PARENT_FILES or sum(len(body.encode()) for body in files.values())
            > joint_owner.MAX_PROJECT_BYTES):
        _fail("complete parent shared project exceeds transport bounds")
    if _parent_shared_pins() != pins:
        _fail("parent shared implementation changed during preparation")
    manifest = contracts.seal_record({
        "schema": PARENT_SCHEMA, "profile": PARENT_PROFILE, "toolchain": toolchain,
        "population": copied["expected_population"], "input_commitment_sha256": commitment,
        "components": components, "definition_modules": [definitions[key] for key in sorted(definitions)],
        "module_bindings": [{"module": module, "module_path": module.replace(".", "/") + ".lean",
            "module_sha256": _sha(fragments[module]["fact"]["body"].encode()),
            "contributors": fragments[module]["contributors"]} for module in sorted(fragments)],
        "expected_modules": ordered, "module_imports": imports,
        "file_sha256": {name: _sha(body.encode()) for name, body in sorted(files.items())},
        "producer_pins": pins, "native_producer_pins": native_pins,
        "preparation_only": True, "lean_compilation_status": "not_run", "proof_status": "pending",
        "child_file_policy": {
            "retained": "Exact child manifest, input binding, Prelude and fragment bytes.",
            "replaced": ["lakefile.toml", "LegalCorpusParent.lean"],
            "mapping": "Each child's original_file_mapping explicitly marks replaced files as null."},
        "theorem_assumptions": [
            "Every child's explicit Interpretation, carrier, time, definition and alias premises remain unchanged.",
            "An aggregate root imports conditional modules; no globally satisfiable interpretation or governing law is established.",
            "Sharing transfers neither source authenticity, meaning review nor legal authority between contributors.",
            "This profile prepares files only; native and incremental qualification have not run."],
        **PARENT_FALSE_FLAGS,
    })
    raw = canonical_dag_json_bytes(manifest)
    # Enforce the existing record transport's byte/node/depth bounds now, not
    # only when a caller later tries to write or parse this preparation.
    contracts.load_record_bytes(raw, expected_sha256=_sha(raw))
    return ParentSharedCorpusPreparation(raw.decode(), tuple(sorted(files.items())))


def prepare_parent_shared_definition_use_corpus_v1(component_inputs, *, expected_population, toolchain):
    """Replay complete parent reviews and share only identical source-bound modules."""
    original = dict(component_inputs=component_inputs, expected_population=expected_population, toolchain=toolchain)
    return _parent_shared_operation(original, _parent_shared_prepare)


def _parent_shared_validate(copied, commitment):
    raw = copied["offered"]["manifest_json"].encode()
    manifest = contracts.load_record_bytes(raw, expected_sha256=_sha(raw))
    contracts.validate_record(manifest, schema=PARENT_SCHEMA, fields=PARENT_FIELDS)
    expected = _parent_shared_prepare(copied, commitment)
    if copied["offered"] != _parent_shared_offered(expected):
        _fail("parent shared project differs from complete independent regeneration")
    return expected


def validate_parent_shared_definition_use_corpus_v1(
        preparation, *, component_inputs, expected_population, toolchain):
    original = dict(component_inputs=component_inputs, expected_population=expected_population, toolchain=toolchain)
    return _parent_shared_operation(original, _parent_shared_validate, preparation)


def _parent_shared_load(directory, expected_manifest_sha256, copied, commitment):
    expected = _parent_shared_prepare(copied, commitment)
    files = joint_owner._read_files(directory, {name for name, _ in expected.files}
        | {joint_owner.MANIFEST_FILE}, maximum_files=MAX_PARENT_FILES)
    raw = files.pop(joint_owner.MANIFEST_FILE)
    contracts.load_record_bytes(raw, expected_sha256=expected_manifest_sha256)
    if (raw != expected.manifest_json.encode()
            or files != {name: body.encode() for name, body in expected.files}):
        _fail("parent shared transport differs from complete independent regeneration")
    return expected


def load_parent_shared_definition_use_corpus_v1(
        directory, *, expected_manifest_sha256, component_inputs, expected_population, toolchain):
    original = dict(component_inputs=component_inputs, expected_population=expected_population, toolchain=toolchain)
    return _parent_shared_operation(original, lambda copied, commitment:
        _parent_shared_load(directory, expected_manifest_sha256, copied, commitment))


def write_parent_shared_definition_use_corpus_v1(
        preparation, directory, *, component_inputs, expected_population, toolchain):
    original = dict(component_inputs=component_inputs, expected_population=expected_population, toolchain=toolchain)
    def write(copied, commitment):
        checked = _parent_shared_validate(copied, commitment)
        def readback(root, raw):
            _parent_shared_load(root, _sha(raw), copied, commitment)
        return joint_owner._write_project(checked, directory, readback=readback,
                                           maximum_files=MAX_PARENT_FILES)
    return _parent_shared_operation(original, write, preparation)


def export_parent_shared_replay_inputs_v1(
        preparation, *, component_inputs, expected_population, toolchain,
        expected_manifest_sha256, max_bytes=parent_owner.MAX_PARENT_REPLAY_BYTES):
    """Retain complete public replay arguments for an independently pinned project.

    Export replays the original public source/review inputs and the existing
    complete project regeneration. The typed payload preserves original public
    signatures, byte bodies, evaluation time and physical-source locators. It
    copies no physical files and grants no current-trust or build authority.
    """
    contracts.require_int(max_bytes, "parent shared replay byte bound", minimum=1,
                          maximum=parent_owner.MAX_PARENT_REPLAY_BYTES)
    contracts.require_sha256(expected_manifest_sha256, "expected parent shared manifest SHA256")
    original = dict(component_inputs=component_inputs,
                    expected_population=expected_population, toolchain=toolchain)

    def export(copied, commitment):
        raw = copied["offered"]["manifest_json"].encode("utf-8")
        if _sha(raw) != expected_manifest_sha256:
            _fail("parent shared replay manifest differs from independent pin")
        _parent_shared_validate(copied, commitment)
        inputs = {key: copied[key] for key in PARENT_REPLAY_INPUT_FIELDS}
        return parent_owner.encode_parent_replay_value_v1({
            "schema": PARENT_REPLAY_SCHEMA, "profile": PARENT_REPLAY_PROFILE,
            "manifest_sha256": expected_manifest_sha256,
            "input_commitment_sha256": commitment, "inputs": inputs,
        }, max_bytes=max_bytes)

    return _parent_shared_operation(original, export, preparation)


def load_parent_shared_replay_inputs_v1(
        payload, *, expected_payload_sha256, expected_payload_bytes,
        expected_input_commitment_sha256, expected_manifest_sha256,
        max_bytes=parent_owner.MAX_PARENT_REPLAY_BYTES):
    """Decode pinned historical input data, without source or review validation.

    The result contains only the three detached public preparation arguments.
    Retain the original physical artifacts at their original locators. Call the
    unchanged public preparation/validation APIs separately; a saved registry,
    policy and evaluation time do not establish a later current-trust decision.
    The manifest pin is SHA256 of the exact preparation manifest bytes, not a
    native preparation or compilation-receipt identity.
    """
    contracts.require_int(max_bytes, "parent shared replay byte bound", minimum=1,
                          maximum=parent_owner.MAX_PARENT_REPLAY_BYTES)
    contracts.require_int(expected_payload_bytes, "expected parent shared replay bytes",
                          minimum=1, maximum=max_bytes)
    contracts.require_sha256(expected_payload_sha256, "expected parent shared replay SHA256")
    contracts.require_sha256(expected_input_commitment_sha256,
                             "expected parent shared input commitment SHA256")
    contracts.require_sha256(expected_manifest_sha256, "expected parent shared manifest SHA256")
    if type(payload) is not bytes or len(payload) != expected_payload_bytes:
        _fail("parent shared replay bytes differ from independent length")
    envelope = parent_owner.decode_parent_replay_value_v1(payload,
        expected_payload_sha256=expected_payload_sha256, max_bytes=max_bytes)
    contracts.require_keys(envelope, PARENT_REPLAY_FIELDS, "parent shared replay envelope")
    if (envelope["schema"] != PARENT_REPLAY_SCHEMA
            or envelope["profile"] != PARENT_REPLAY_PROFILE):
        _fail("parent shared replay schema or profile differs")
    contracts.require_sha256(envelope["manifest_sha256"], "parent shared replay manifest SHA256")
    contracts.require_sha256(envelope["input_commitment_sha256"],
                             "parent shared replay input commitment SHA256")
    if (envelope["manifest_sha256"] != expected_manifest_sha256
            or envelope["input_commitment_sha256"] != expected_input_commitment_sha256):
        _fail("parent shared replay identities differ from independent pins")
    original = envelope["inputs"]
    contracts.require_keys(original, PARENT_REPLAY_INPUT_FIELDS, "parent shared replay inputs")
    copied, _, commitment = _parent_shared_capture(original, None)
    _parent_shared_check_inputs(copied)
    if commitment != expected_input_commitment_sha256:
        _fail("parent shared replay input commitment differs from complete decoded inputs")
    return {key: copied[key] for key in PARENT_REPLAY_INPUT_FIELDS}


def _module(prefix, identity):
    return "LegalCorpus." + prefix + _sha(identity.encode("utf-8"))


def _file(module, imports, body):
    return "\n".join("import " + item for item in imports) + "\nnamespace " + module + "\n" + body + "\nend " + module + "\n"


def prepare_shared_definition_corpus(candidate_inputs, *, expected_population, toolchain):
    """Share exact explicit definitions while preserving every original norm."""
    pins = _pins()
    original = joint_owner.prepare_definition_norm_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    original_manifest = original.to_dict()
    from . import legal_source_definition_norm_lake as native

    routes, emitter = native.bridge.routes, native.emitters
    files = {
        "lakefile.toml": 'name = "legal_corpus_shared"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCorpus"]\n',
        "lean-toolchain": toolchain + "\n",
        "LegalCorpus/Prelude.lean": "namespace LegalCorpus\n" + emitter.PRELUDE + "\nend LegalCorpus\n",
        "definition-inputs.json": dict(original.files)["definition-inputs.json"],
    }
    definitions, norms = {}, []
    for inputs, population, binding in zip(
            candidate_inputs, original_manifest["population"], original_manifest["bindings"], strict=True):
        candidate = contracts.load_record_bytes(inputs["candidate_raw"], expected_sha256=population["candidate_sha256"])
        report = contracts.load_record_bytes(inputs["report_raw"], expected_sha256=population["report_sha256"])
        definition_ast = candidate["definition_record"]["native_ast"]
        norm_ast = candidate["norm_record"]["native_ast"]
        joint_ast = candidate["ast_record"]["native_ast"]
        if (joint_ast.get("node_type") != "BinaryFormula" or joint_ast.get("operator", {}).get("value") != "∧"
                or joint_ast.get("left") != definition_ast or joint_ast.get("right") != norm_ast):
            _fail("shared components do not preserve the original ordered joint AST")
        key = _sharing_key(candidate)
        key_cid = key["record_cid"]
        definition_module = _module("Definition", key_cid)
        contributor = {
            "ordinal": binding["ordinal"], "candidate_cid": candidate["record_cid"],
            "definition_record_cid": candidate["definition_record"]["record_cid"],
            "interpretation_cid": candidate["report_record"]["record_cid"],
            "term_record_cid": candidate["term_record"]["record_cid"],
            "symbol_record_cid": candidate["symbol_record"]["record_cid"],
        }
        if key_cid not in definitions:
            fragment = routes.prepare_native_fragment(
                family="fol", formula=report["bound_definition_native"]["formula"], expected_ast=definition_ast)
            body = emitter.FormulaRenderer().formula(definition_ast["formula"]["right"], {"x": "entity"})
            body_declaration = ("def bodyAt {Entity Agent : Type} (i : Interpretation Entity Agent) "
                                "(entity : Entity) : Nat → Prop := " + body)
            path = definition_module.replace(".", "/") + ".lean"
            files[path] = _file(definition_module, ["LegalCorpus.Prelude"], fragment["lean_body"] + "\n" + body_declaration)
            definitions[key_cid] = {
                "sharing_key": key, "sharing_key_cid": key_cid,
                "module": definition_module, "module_path": path,
                "qualified_declaration": definition_module + ".formula_0",
                "body_declaration": definition_module + ".bodyAt",
                "contributors": [], "native_fragment": fragment,
                "module_sha256": _sha(files[path].encode("utf-8")),
            }
        definitions[key_cid]["contributors"].append(contributor)
        parsed = routes.qualification._strict_tdfol(report["native"]["formula"])[0]
        fragment = routes.prepare_native_fragment(
            family=report["family"], formula=parsed.right.to_string(), expected_ast=norm_ast)
        consequence = emitter.FormulaRenderer().formula(norm_ast["formula"]["right"], {"x": "entity"})
        module = _module("Norm", candidate["record_cid"])
        path = module.replace(".", "/") + ".lean"
        body = (fragment["lean_body"] + "\n"
            + "def modalActionAt {Entity Agent : Type} (i : Interpretation Entity Agent) "
              "(entity : Entity) : Nat → Prop := " + consequence + "\n"
            + "def jointAt {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := "
              "fun t => " + definition_module + ".formula_0 i t ∧ formula_0 i t\n"
            + "theorem consequence_of_definition {Entity Agent : Type} (i : Interpretation Entity Agent) "
              "(t : Nat) (entity : Entity)\n"
            + "    (hDef : " + definition_module + ".formula_0 i t) (hNorm : formula_0 i t)\n"
            + "    (hBody : " + definition_module + ".bodyAt i entity t) : modalActionAt i entity t := by\n"
            + "  exact hNorm entity ((hDef entity).mpr hBody)\n"
            + "#print axioms consequence_of_definition")
        files[path] = _file(module, [definition_module], body)
        norms.append({
            "ordinal": binding["ordinal"], "candidate_cid": candidate["record_cid"],
            "definition_key_cid": key_cid, "definition_module": definition_module,
            "module": module, "module_path": path,
            "qualified_declaration": module + ".formula_0",
            "joint_declaration": module + ".jointAt",
            "composition_theorem": module + ".consequence_of_definition",
            "module_sha256": _sha(files[path].encode("utf-8")),
            "native_norm_fragment": fragment, "original_joint_binding": binding,
            "original_joint_lean_sha256": _sha(candidate["ast_record"]["lean_body"].encode("utf-8")),
        })
    definition_rows = [definitions[key] for key in sorted(definitions)]
    files["LegalCorpus.lean"] = "\n".join("import " + row["module"] for row in norms) + "\n"
    if (len(files) > MAX_FILES or sum(len(body.encode("utf-8")) for body in files.values()) > joint_owner.MAX_PROJECT_BYTES
            or any(native.shared._REFUSED.search(body) for name, body in files.items() if name.endswith(".lean"))):
        _fail("unsupported or oversized complete shared Lean project")
    if _pins() != pins:
        _fail("shared corpus implementation changed during preparation")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": toolchain,
        "population": original_manifest["population"], "population_cid": original_manifest["population_cid"],
        "original_preparation_cid": original_manifest["record_cid"],
        "definition_modules": definition_rows, "norm_bindings": norms,
        "expected_modules": ["LegalCorpus.Prelude", *[row["module"] for row in definition_rows],
                             *[row["module"] for row in norms], "LegalCorpus"],
        "file_sha256": {name: _sha(body.encode("utf-8")) for name, body in sorted(files.items())},
        "producer_pins": pins, "native_producer_pins": original_manifest["native_preparation_manifest"]["producer_pins"],
        "shared_definition_deduplication": True, "external_definition_resolution": False,
        "preparation_only": True,
        "theorem_assumptions": ["The exact shared definition holds at the evaluation time.",
            "The universally guarded norm holds at that same time under the same interpretation.",
            "The declared definition body holds for the supplied entity at that time.",
            "The conclusion is the parameterized modal action; it does not establish actual action truth or legal truth."],
        **FALSE_FLAGS,
    })
    return SharedCorpusPreparation(canonical_dag_json_bytes(manifest).decode("utf-8"), tuple(sorted(files.items())))


def validate_shared_definition_corpus(preparation, *, candidate_inputs, expected_population, toolchain):
    if type(preparation) is not SharedCorpusPreparation:
        _fail("typed shared corpus preparation required")
    contracts.validate_record(preparation.to_dict(), schema=SCHEMA, fields=FIELDS)
    expected = prepare_shared_definition_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    if preparation != expected:
        _fail("shared corpus differs from independent complete regeneration")
    return preparation


def load_shared_definition_corpus(directory, *, expected_manifest_sha256,
                                  candidate_inputs, expected_population, toolchain):
    expected = prepare_shared_definition_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    files = joint_owner._read_files(directory, {name for name, _ in expected.files}
                                   | {joint_owner.MANIFEST_FILE}, maximum_files=MAX_FILES)
    raw = files.pop(joint_owner.MANIFEST_FILE)
    contracts.load_record_bytes(raw, expected_sha256=expected_manifest_sha256)
    if raw != expected.manifest_json.encode("utf-8") or files != {
            name: body.encode("utf-8") for name, body in expected.files}:
        _fail("shared corpus project differs from independent complete regeneration")
    return expected


def write_shared_definition_corpus(preparation, directory, *, candidate_inputs, expected_population, toolchain):
    checked = validate_shared_definition_corpus(
        preparation, candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)

    def readback(root, raw):
        load_shared_definition_corpus(root, expected_manifest_sha256=_sha(raw),
            candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)

    return joint_owner._write_project(checked, directory, readback=readback, maximum_files=MAX_FILES)


def build_shared_definition_corpus(preparation, *, candidate_inputs, expected_population, toolchain,
                                   lake_executable, output_directory, timeout_seconds=60, cancellation=None):
    """Compile exact bound files; callers acquire the shared validation lease."""
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        _fail("bounded native build timeout required")
    output = joint_owner._path(output_directory)
    joint_owner._check_directories(output.parent, allow_missing=True)
    if output.exists() or output.is_symlink():
        _fail("fresh shared build output directory required")
    checked = validate_shared_definition_corpus(
        preparation, candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    from . import legal_source_definition_norm_lake as native

    executable, binaries, probes = native.shared._installed_toolchain(lake_executable, toolchain)
    manifest = checked.to_dict()
    command = (str(executable), "--offline", "--no-cache", "build", "legal")
    modules = manifest["expected_modules"]
    paths = tuple(".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" for module in modules)
    result = native.process.BoundedToolRunner().run(native.process.ToolRunRequest(
        argv=command, input_files=dict(checked.files), output_paths=paths,
        environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"},
        limits=native.process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=262144,
            max_input_bytes=joint_owner.MAX_PROJECT_BYTES, max_workspace_bytes=128 * 1024**2,
            max_output_files=2 * joint_owner.MAX_CANDIDATES + 2)),
        **({"cancellation": cancellation} if cancellation is not None else {}))
    post_run_error = None
    try:
        validate_shared_definition_corpus(
            checked, candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
        post_run_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    binary_error = None
    try:
        unchanged = all(_sha(Path(name).read_bytes()) == digest for name, digest in binaries.items())
    except OSError as error:
        unchanged = False
        binary_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    coverage = set(result.output_files) == set(paths) and all(result.output_files.values())
    axioms = {}
    for row in manifest["norm_bindings"]:
        theorem = row["composition_theorem"]
        if "'" + theorem + "' does not depend on any axioms" in result.stdout:
            axioms[theorem] = []
    passed = bool(result.ok and result.pid is not None and tuple(result.command) == command and coverage and unchanged
        and len(axioms) == len(manifest["norm_bindings"]) and not result.output_truncated
        and not result.workspace_limit_exceeded and result.workspace_cleaned and not result.error
        and post_run_error is None and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
    receipt = contracts.seal_record({
        "schema": BUILD_SCHEMA, "profile": PROFILE, "preparation_cid": manifest["record_cid"],
        "preparation_manifest_sha256": _sha(checked.manifest_json.encode("utf-8")),
        "toolchain": toolchain, "command": list(command), "returncode": result.returncode,
        "pid": result.pid, "expected_modules": modules,
        "compiled_modules": [module for module, path in zip(modules, paths, strict=True) if path in result.output_files],
        "manifest_coverage_passed": bool(coverage), "binary_sha256": binaries, "binaries_unchanged": unchanged,
        "post_run_validation_passed": post_run_error is None, "post_run_validation_error": post_run_error,
        "binary_recheck_error": binary_error, "execution_error": result.error,
        "version_probes": probes, "artifact_sha256": {name: _sha(raw) for name, raw in result.output_files.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                           for name in paths if name in result.output_files},
        "theorem_axiom_dependencies": axioms, "theorem_assumptions": manifest["theorem_assumptions"],
        "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out,
        "output_truncated": result.output_truncated, "workspace_limit_exceeded": result.workspace_limit_exceeded,
        "resource_exhausted": result.resource_exhausted, "workspace_cleaned": result.workspace_cleaned,
        "cancelled": result.cancelled, "unavailable": result.unavailable,
        "process_tree_terminated": result.process_tree_terminated, "build_passed": passed,
        "composition_obligations_checked": passed,
        **(FALSE_FLAGS | {"backend_executed": result.pid is not None, "lean_compilation_verified": passed}),
    })
    _write_frozen_project(checked, output / "project")
    _write_compiled(output / "compiled", {name.removeprefix(".lake/build/lib/lean/"): result.output_files[name]
                                          for name in paths if name in result.output_files})
    with (output / "build-receipt.json").open("xb") as destination:
        destination.write(canonical_dag_json_bytes(receipt))
    return receipt


def _write_frozen_project(preparation, directory):
    """Retain exactly executed inputs, including failed post-run qualification."""
    expected_files = {name: body.encode("utf-8") for name, body in preparation.files}
    expected_files[joint_owner.MANIFEST_FILE] = preparation.manifest_json.encode("utf-8")

    def readback(root, raw):
        observed = joint_owner._read_files(root, set(expected_files), maximum_files=MAX_FILES)
        if raw != expected_files[joint_owner.MANIFEST_FILE] or observed != expected_files:
            _fail("frozen executed project failed exact readback")

    return joint_owner._write_project(preparation, directory, readback=readback, maximum_files=MAX_FILES)


def _write_compiled(directory, artifacts):
    directory.mkdir(mode=0o700, exist_ok=False)
    root_fd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    descriptors = {"": root_fd}
    try:
        for name, raw in artifacts.items():
            dirname, _, basename = name.rpartition("/")
            if dirname and dirname not in descriptors:
                os.mkdir(dirname, mode=0o700, dir_fd=root_fd)
                descriptors[dirname] = os.open(
                    dirname, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=root_fd)
            joint_owner._write_new_file(descriptors[dirname], basename, raw)
        for fd in descriptors.values():
            os.fsync(fd)
    finally:
        for fd in reversed(list(descriptors.values())):
            os.close(fd)


__all__ = ["SharedCorpusPreparation", "prepare_shared_definition_corpus", "validate_shared_definition_corpus",
    "write_shared_definition_corpus", "load_shared_definition_corpus", "build_shared_definition_corpus",
    "ParentSharedCorpusPreparation", "prepare_parent_shared_definition_use_corpus_v1",
    "validate_parent_shared_definition_use_corpus_v1", "load_parent_shared_definition_use_corpus_v1",
    "write_parent_shared_definition_use_corpus_v1"]
