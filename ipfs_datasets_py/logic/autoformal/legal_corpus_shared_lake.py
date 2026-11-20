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


# This profile composes independent preservation witnesses, not the older
# conditional definition-use theorems. Its lazy owners and pins deliberately do
# not enlarge any legacy operation's exact producer set.
REVIEWED_PRESERVATION_SCHEMA = "legal-corpus-reviewed-preservation-preparation/v2"
REVIEWED_PRESERVATION_PROFILE = "reviewed-multi-unit-object-relational-preservation/v2"
REVIEWED_SOURCE_USE_IDENTITY_PROFILE = "reviewed-source-use/v1"
REVIEWED_SOURCE_USE_PRESERVATION_PROFILE = REVIEWED_PRESERVATION_PROFILE + "+reviewed-source-use/v1"
REVIEWED_PRESERVATION_ROOT = "LegalReviewedNormPreservation"
MAX_REVIEWED_PRESERVATION_UNITS = 8
MAX_REVIEWED_PRESERVATION_FILES = 9 * MAX_REVIEWED_PRESERVATION_UNITS + 6
MAX_REVIEWED_PRESERVATION_MODULES = MAX_REVIEWED_PRESERVATION_UNITS + 3
MAX_REVIEWED_PRESERVATION_OBLIGATIONS = 5 * MAX_REVIEWED_PRESERVATION_UNITS
_REVIEWED_PRESERVATION_LEAVES = (
    "native_value_exact", "native_ast_closed", "denotation_matches_native",
    "typed_source_lowering_exact", "role_denotation_matches_native",
)
_REVIEWED_PRESERVATION_SELF_PIN = _sha(Path(__file__).read_bytes())


@dataclass(frozen=True)
class ReviewedPreservationCorpusPreparation:
    """A replay-bound project proposal with no build or admission authority."""

    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        raw = self.manifest_json.encode("utf-8")
        return contracts.load_record_bytes(raw, expected_sha256=_sha(raw))


def _reviewed_preservation_owners():
    from . import corpus_norm_definition_adapter, legal_native_ast_preservation
    from . import legal_norm_content_adjudication_v1
    return corpus_norm_definition_adapter, legal_norm_content_adjudication_v1, legal_native_ast_preservation


def _reviewed_preservation_pins(owners):
    graph, admission, native = owners
    if _sha(Path(__file__).read_bytes()) != _REVIEWED_PRESERVATION_SELF_PIN:
        _fail("reviewed preservation owner changed since import")
    pins = dict(graph._reviewed_graph_pins(admission))
    for module in (native,):
        path = str(Path(module.__file__).resolve())
        digest = _sha(Path(path).read_bytes())
        if path in pins and pins[path] != digest:
            _fail("reviewed preservation producer observations disagree")
        pins[path] = digest
    pins[str(Path(__file__).resolve())] = _REVIEWED_PRESERVATION_SELF_PIN
    return pins


def _reviewed_preservation_offered(preparation):
    if type(preparation) is not ReviewedPreservationCorpusPreparation:
        _fail("typed reviewed preservation preparation required")
    if (type(preparation.manifest_json) is not str
            or len(preparation.manifest_json.encode("utf-8")) > contracts.MAX_RECORD_BYTES
            or type(preparation.files) is not tuple
            or not 1 <= len(preparation.files) <= MAX_REVIEWED_PRESERVATION_FILES):
        _fail("bounded reviewed preservation manifest and files required")
    pairs, names, total = [], [], 0
    for pair in preparation.files:
        if type(pair) is not tuple or len(pair) != 2 or any(type(value) is not str for value in pair):
            _fail("ordinary immutable reviewed preservation file pairs required")
        name, body = pair
        if (len(name) > 256 or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)?", name) is None
                or any(part in (".", "..") for part in name.split("/"))):
            _fail("bounded safe reviewed preservation paths required")
        total += len(body.encode("utf-8"))
        if total > joint_owner.MAX_PROJECT_BYTES:
            _fail("reviewed preservation project byte bound exceeded")
        names.append(name)
        pairs.append([name, body])
    if names != sorted(set(names)):
        _fail("sorted unique reviewed preservation file paths required")
    return {"manifest_json": preparation.manifest_json, "files": pairs}


def reviewed_preservation_corpus_sha256(preparation):
    """Bind every UTF8 byte of the manifest, active project and child companions."""
    return _sha(canonical_dag_json_bytes(_reviewed_preservation_offered(preparation)))


def _reviewed_preservation_units(graph, admission, replay, *, version=2):
    if type(version) is not int or version not in (2, 3):
        _fail("explicit reviewed preservation unit version required")
    declaration = replay["preparation_inputs"]["declaration"]
    if not {"formalization", "proof_obligation"}.issubset(admission["permitted_uses"]):
        _fail("explicit reviewed formalization and proof-obligation permissions required")
    units = declaration["units"]
    if not 3 <= len(units) <= MAX_REVIEWED_PRESERVATION_UNITS:
        _fail("reviewed preservation requires three to eight complete source units")
    ids = [row["unit_id"] for row in units]
    groups = (admission["units"], graph["unit_records"], graph["ast_records"])
    if any([row["unit_id"] for row in group] != ids for group in groups):
        _fail("complete ordered reviewed admission and graph unit bijection required")
    if (set(replay["preparation_inputs"]["relational_inputs"]) != set(ids)
            or set(replay["preparation_inputs"]["source_inputs"]) != set(ids)):
        _fail("complete exact source and relational replay inputs required")
    if (graph["source_versions"] != [row["source_version"] for row in units]
            or graph["source_occurrences"] != [row["occurrence"] for row in units]):
        _fail("reviewed graph source version and occurrence order differs")
    context = declaration["governing_context"]
    if (any(graph["scope_record"][key] != value for key, value in context.items())
            or graph["scope_record"]["interpretation_id"] != declaration["interpretation_id"]):
        _fail("one exact reviewed governing context and interpretation required")
    signature_header, predicate_ledger, index = None, {}, []
    signature_headers = []
    for ordinal, (unit, admitted, graph_unit, graph_ast) in enumerate(zip(units, *groups, strict=True)):
        ir = admitted["canonical_ir"]
        binding = {"source_version_cid": unit["source_version"]["record_cid"],
            "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}
        ir_bytes = canonical_dag_json_bytes(ir)
        if (ir["source_binding"] != binding or admitted["occurrence_cid"] != binding["occurrence_cid"]
                or ir["governing_context"] != context or ir["interpretation_id"] != declaration["interpretation_id"]
                or ir["assumptions"] != [] or graph_ast["ast_json"].encode("utf-8") != ir_bytes
                or graph_ast["ast_sha256"] != _sha(ir_bytes)
                or graph_ast["source_occurrence_cid"] != binding["occurrence_cid"]
                or graph_unit["ast_record_cid"] != graph_ast["record_cid"]
                or graph_unit["source_version_cid"] != binding["source_version_cid"]
                or graph_unit["source_occurrence_cid"] != binding["occurrence_cid"]
                or graph_unit["scope_record_cid"] != graph["scope_record"]["record_cid"]
                or graph_unit["interpretation_record_cid"] != graph["interpretation_record"]["record_cid"]):
            _fail("complete unit source, ordered IR, origin and reviewed scope binding differs")
        inputs = replay["preparation_inputs"]["relational_inputs"][unit["unit_id"]]
        report = inputs["report"]
        if (report["typed_expression"] != ir["typed_expression"]
                or report["argument_roles"] != ir["argument_roles"]
                or admitted["argument_roles"] != ir["argument_roles"]
                or admitted["relational_profile"] != report["profile"]
                or graph_unit["relational_request_sha256"] != unit["relational_request_sha256"]):
            _fail("complete unit report, ordered roles and request identity differs")
        signature = ir["typed_expression"]["signature"]
        header = {key: value for key, value in signature.items() if key != "symbols"}
        if version == 2:
            if signature_header is None:
                signature_header = header
            elif header != signature_header:
                _fail("shared Object signature headers differ")
            namespace = None
            symbol_ledger = predicate_ledger
        else:
            # A signature ID, sort ordering and source profile remain part of
            # each unit's model. Equal spellings across different models are
            # not a declaration merge or a governing-definition theorem.
            namespace = report["profile"] + ":" + _sha(canonical_dag_json_bytes(header))
            signature_headers.append({"unit_id": unit["unit_id"],
                "relational_profile": report["profile"], "signature_header": header,
                "signature_namespace_sha256": _sha(canonical_dag_json_bytes({
                    "relational_profile": report["profile"], "signature_header": header}))})
            if namespace not in predicate_ledger:
                predicate_ledger[namespace] = {"relational_profile": report["profile"],
                    "signature_header": header, "unit_ids": [], "predicates": {}}
            namespace_ledger = predicate_ledger[namespace]
            if (namespace_ledger["relational_profile"] != report["profile"]
                    or namespace_ledger["signature_header"] != header):
                _fail("reviewed signature namespace collision")
            namespace_ledger["unit_ids"].append(unit["unit_id"])
            symbol_ledger = namespace_ledger["predicates"]
        roles = {row["symbol"]: row["roles"] for row in ir["argument_roles"]}
        for symbol in signature["symbols"]:
            entry = {"declaration": symbol, "ordered_argument_roles": roles[symbol["name"]]}
            name = symbol["name"]
            if name in symbol_ledger and symbol_ledger[name] != entry:
                _fail("shared predicate signature or ordered argument roles differ")
            symbol_ledger[name] = entry
        index.append({"ordinal": ordinal, "unit_id": unit["unit_id"], "kind": unit["kind"],
            "source_version_cid": binding["source_version_cid"], "source_occurrence_cid": binding["occurrence_cid"],
            "document_revision": unit["document_revision"], "parent_unit_ids": unit["parent_unit_ids"],
            "source_text_sha256": _sha(admitted["source_text"].encode("utf-8")),
            "graph_unit_record_cid": graph_unit["record_cid"], "graph_ast_record_cid": graph_ast["record_cid"],
            "complete_ir_sha256": _sha(ir_bytes), "scope_record_cid": graph_unit["scope_record_cid"],
            "interpretation_record_cid": graph_unit["interpretation_record_cid"],
            "signature_id": signature["signature_id"],
            "relational_request_sha256": unit["relational_request_sha256"],
            "relational_report_sha256": inputs["expected_report_sha256"]})
        if version == 3:
            index[-1].update(relational_profile=report["profile"], signature_header=header,
                signature_namespace_sha256=signature_headers[-1]["signature_namespace_sha256"])
    return index, signature_header if version == 2 else signature_headers, predicate_ledger


def _reviewed_source_use_profile(instance_identity_profile, *, version):
    """Select an explicit identity domain; saved preparations cannot opt in."""
    if (instance_identity_profile is not None and (type(instance_identity_profile) is not str
            or instance_identity_profile != "reviewed-source-use/v1")):
        _fail("explicit reviewed source-use identity profile required")
    if instance_identity_profile is None:
        return REVIEWED_PRESERVATION_PROFILE if version == 2 else REVIEWED_MIXED_PRESERVATION_PROFILE
    if (REVIEWED_SOURCE_USE_IDENTITY_PROFILE != "reviewed-source-use/v1"
            or REVIEWED_SOURCE_USE_PRESERVATION_PROFILE !=
                "reviewed-multi-unit-object-relational-preservation/v2+reviewed-source-use/v1"
            or REVIEWED_MIXED_SOURCE_USE_PRESERVATION_PROFILE !=
                "reviewed-multi-unit-mixed-relational-preservation/v3+reviewed-source-use/v1"):
        _fail("fixed reviewed source-use identity domains required")
    return (REVIEWED_SOURCE_USE_PRESERVATION_PROFILE if version == 2
        else REVIEWED_MIXED_SOURCE_USE_PRESERVATION_PROFILE)


def _reviewed_source_use_child_args(item):
    """Derive custody only from the complete, currently replayed unit index."""
    binding = {"schema": "legal-native-reviewed-source-use-binding/v1",
        **{key: item[key] for key in ("unit_id", "source_version_cid", "source_occurrence_cid",
            "complete_ir_sha256", "graph_unit_record_cid", "graph_ast_record_cid",
            "scope_record_cid", "interpretation_record_cid")}}
    return {"source_use_binding": binding,
        "expected_source_use_binding_sha256": _sha(canonical_dag_json_bytes(binding))}


def _reviewed_source_use_child_echo(manifest, item, child_args, instance_identity_profile):
    keys = ("source_use_binding", "source_use_binding_sha256", "instance_identity_profile")
    if instance_identity_profile is None:
        if any(key in manifest for key in keys):
            _fail("legacy child cannot acquire reviewed source-use identity")
        return {}
    expected = _reviewed_source_use_child_args(item)
    if any(child_args.get(key) != value for key, value in expected.items()):
        _fail("derived reviewed source-use binding changed during child preparation")
    binding = {"source_use_binding": expected["source_use_binding"],
        "source_use_binding_sha256": expected["expected_source_use_binding_sha256"]}
    if any(manifest.get(key) != value for key, value in
            {**binding, "instance_identity_profile": instance_identity_profile}.items()):
        _fail("child reviewed source-use binding differs from current complete replay")
    return binding


def _reviewed_preservation_project(graph, admission, replay, owners, pins, commitment,
        expected_graph_sha256, expected_admission_sha256, toolchain, *, instance_identity_profile=None):
    profile = _reviewed_source_use_profile(instance_identity_profile, version=2)
    _, _, native = owners
    index, signature_header, predicates = _reviewed_preservation_units(graph, admission, replay)
    files, modules, obligations, units, native_pins = {}, [], [], [], {}
    imports = {}

    def add(name, body, *, shared=False):
        if type(name) is not str or type(body) is not str:
            _fail("ordinary reviewed preservation project files required")
        if name in files:
            if shared and files[name] == body:
                return
            _fail("reviewed preservation path or instance declaration collision")
        if (len(files) >= MAX_REVIEWED_PRESERVATION_FILES
                or sum(len(text.encode("utf-8")) for text in files.values()) + len(body.encode("utf-8"))
                    > joint_owner.MAX_PROJECT_BYTES):
            _fail("reviewed preservation aggregate file or UTF8 byte bound exceeded")
        files[name] = body

    common = [native.RELATIONAL_PROJECT_ROOT + ".Prelude", native.RELATIONAL_PROJECT_ROOT + ".Semantics"]
    for item in index:
        inputs = replay["preparation_inputs"]["relational_inputs"][item["unit_id"]]
        child_args = dict(expected_report_sha256=item["relational_report_sha256"],
            expected_request_sha256=item["relational_request_sha256"], toolchain=toolchain)
        if instance_identity_profile is not None:
            child_args.update(_reviewed_source_use_child_args(item))
        child = native.prepare_relational_ast_preservation(inputs["report"], inputs["request_raw"], **child_args)
        child_sha = native.preparation_sha256(child)
        native.validate_relational_ast_preservation(child, inputs["report"], inputs["request_raw"],
            expected_preparation_sha256=child_sha, **child_args)
        manifest, child_files = child.to_dict(), dict(child.files)
        source_use = _reviewed_source_use_child_echo(manifest, item, child_args, instance_identity_profile)
        child_profile = ("typed-relational-deontic-native-preservation/v1+reviewed-source-use/v1"
            if instance_identity_profile is not None else native.RELATIONAL_PROFILE)
        instance_modules = [module for module in manifest["expected_modules"]
            if module not in common + [native.RELATIONAL_PROJECT_ROOT]]
        if (manifest["schema"] != native.SCHEMA or manifest["profile"] != child_profile
                or manifest["family"] != "deontic_fol"
                or manifest["toolchain"] != toolchain or len(instance_modules) != 1
                or manifest["relational_report_sha256"] != item["relational_report_sha256"]
                or manifest["original_request_sha256"] != item["relational_request_sha256"]
                or manifest["preparation_only"] is not True
                or type(manifest["training_mask"]) is not int or manifest["training_mask"] != 0
                or type(manifest["evaluation_gold_mask"]) is not int or manifest["evaluation_gold_mask"] != 0
                or set(manifest["authority"]) != set(native.AUTHORITY)
                or any(value is not False for value in manifest["authority"].values())
                or any(manifest[key] is not False for key in native.FALSE_FLAGS)
                or manifest["support_profile"]["typed_sort"] != "Object"
                or manifest["support_profile"]["native_sort"] is not None
                or manifest["support_profile"]["counting_supported"] is not False
                or manifest["support_profile"]["modal_agent"] is not None
                or manifest["support_profile"]["modal_context"] is not None):
            _fail("unchanged closed Object relational O/P/F preservation child required")
        instance = instance_modules[0]
        if (re.fullmatch(r"LegalRelationalAstPreservation\.Instance[0-9a-f]{64}", instance) is None
                or instance in modules):
            _fail("distinct physical units cannot share an instance or declaration in this profile")
        expected_theorems = [instance + "." + leaf for leaf in _REVIEWED_PRESERVATION_LEAVES]
        expected_imports = {common[0]: [], common[1]: [common[0]], instance: [common[1]],
            native.RELATIONAL_PROJECT_ROOT: [instance]}
        expected_files = {module.replace(".", "/") + ".lean" for module in [*common, instance]}
        expected_files |= {"lakefile.toml", "lean-toolchain", "preservation-inputs.json",
            native.RELATIONAL_PROJECT_ROOT + ".lean"}
        if (manifest["expected_modules"] != [*common, instance, native.RELATIONAL_PROJECT_ROOT]
                or manifest["module_imports"] != expected_imports or manifest["theorems"] != expected_theorems
                or set(child_files) != expected_files or len(child.files) != 7
                or manifest["file_sha256"] != {name: _sha(body.encode("utf-8")) for name, body in child.files}
                or child_files["lean-toolchain"] != toolchain + "\n"
                or child_files[native.RELATIONAL_PROJECT_ROOT + ".lean"] != "import " + instance + "\n"):
            _fail("complete unchanged child project and five ordered preservation obligations required")
        for path, digest in manifest["producer_pins"].items():
            if path in native_pins and native_pins[path] != digest:
                _fail("per-unit native preservation producer pins disagree")
            native_pins[path] = digest
        for module in (*common, instance):
            add(module.replace(".", "/") + ".lean", child_files[module.replace(".", "/") + ".lean"],
                shared=module in common)
        # Keep all seven child files byte-for-byte under unique ordinal paths,
        # including their colliding inputs, child root and child lakefile.
        prefix = "unit-companions/" + format(item["ordinal"], "02d") + "-"
        companions = []
        for ordinal, (name, body) in enumerate(child.files):
            target = prefix + "file-" + format(ordinal, "02d") + ".txt"
            add(target, body)
            companions.append({"original_path": name, "companion_path": target,
                "sha256": _sha(body.encode("utf-8"))})
        manifest_path = prefix + "manifest.json"
        add(manifest_path, child.manifest_json)
        units.append(dict(item, **source_use, child_preparation_sha256=child_sha,
            child_manifest_sha256=_sha(child.manifest_json.encode("utf-8")), child_manifest_path=manifest_path,
            original_child_files=companions, instance_module=instance, preservation_obligations=expected_theorems))
        modules.append(instance)
        obligations.extend(expected_theorems)
        imports[instance] = [common[1]]
    if (len(set(obligations)) != len(index) * 5 or len(obligations) > MAX_REVIEWED_PRESERVATION_OBLIGATIONS
            or len(modules) + 3 > MAX_REVIEWED_PRESERVATION_MODULES):
        _fail("complete distinct bounded unit preservation obligations required")
    root = REVIEWED_PRESERVATION_ROOT
    add(root + ".lean", "".join("import " + module + "\n" for module in modules))
    lake_roots = canonical_dag_json_bytes([*common, *modules, root]).decode("utf-8")
    add("lakefile.toml", 'name = "legal_reviewed_norm_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ' + lake_roots + "\n")
    add("lean-toolchain", toolchain + "\n")
    bindings = {"schema": "legal-corpus-reviewed-preservation-bindings/v2",
        "input_commitment_sha256": commitment, "reviewed_graph_sha256": expected_graph_sha256,
        "reviewed_admission_sha256": expected_admission_sha256, "declaration_sha256": admission["declaration_sha256"],
        "units": units}
    if instance_identity_profile is not None:
        bindings["instance_identity_profile"] = instance_identity_profile
    add("reviewed-input-bindings.json", canonical_dag_json_bytes(bindings).decode("utf-8") + "\n")
    imports.update({common[0]: [], common[1]: [common[0]], root: modules})
    for path, digest in native_pins.items():
        if (path in pins and pins[path] != digest) or _sha(Path(path).read_bytes()) != digest:
            _fail("current native preservation dependencies differ")
    flags = dict(native.FALSE_FLAGS)
    manifest = contracts.seal_record({**bindings, "schema": REVIEWED_PRESERVATION_SCHEMA,
        "profile": profile, "toolchain": toolchain, "target": "legal",
        "provenance_kind": admission["provenance_kind"],
        "scope_record_cid": graph["scope_record"]["record_cid"],
        "interpretation_record_cid": graph["interpretation_record"]["record_cid"],
        "signature_header": signature_header, "predicate_compatibility_ledger": predicates,
        "expected_modules": [*common, *modules, root], "module_imports": imports,
        "preservation_obligations": obligations,
        "file_sha256": {name: _sha(body.encode("utf-8")) for name, body in sorted(files.items())},
        "producer_pins": pins, "native_producer_pins": native_pins,
        "support_profile": {"families": ["deontic_fol"], "typed_sort": "Object", "native_sort": None,
            "modalities": ["O", "P", "F"], "counting_supported": False, "modal_agent": None, "modal_context": None,
            "all_declared_units_required": True, "ordered_units_preserved": True,
            "one_exact_signature_header_including_signature_id": True,
            "signature_symbol_subsets_may_differ": True,
            "overlapping_predicates_require_exact_signatures_and_ordered_roles": True,
            "predicate_compatibility_is_syntactic_only": True, "cross_unit_definition_application_proved": False,
            "source_versions_may_differ_under_exact_common_reviewed_context": True,
            "duplicate_instance_declarations_across_physical_units": "entire_preparation_refused",
            "instance_rewriting_or_deduplication": False, "shared_files": "byte_identical_Prelude_and_Semantics_only",
            "max_units": MAX_REVIEWED_PRESERVATION_UNITS, "max_files": MAX_REVIEWED_PRESERVATION_FILES,
            "max_modules": MAX_REVIEWED_PRESERVATION_MODULES, "max_obligations": MAX_REVIEWED_PRESERVATION_OBLIGATIONS,
            "max_project_utf8_bytes": joint_owner.MAX_PROJECT_BYTES},
        "trust_boundary": ["Current complete reviewed admission and graph inputs are replayed, not inferred.",
            "Every original child file and manifest remains retained; active instance bytes remain unchanged.",
            "Five independent typed/native preservation obligations per unit are proposed, not executed.",
            "Same predicate spelling is syntactic compatibility, not shared legal meaning or definition application.",
            "No alias theorem, desired-equivalence premise, source prose proof, corpus or statutory admission is supplied."],
        "preparation_only": True, "lean_compilation_status": "not_executed", "proof_status": "not_executed",
        "authority": dict(native.AUTHORITY), "semantic_use_eligible": False, "training_mask": 0,
        "evaluation_gold_mask": 0, **flags})
    result = ReviewedPreservationCorpusPreparation(canonical_dag_json_bytes(manifest).decode("utf-8"),
        tuple(sorted(files.items())))
    reviewed_preservation_corpus_sha256(result)
    if any(_sha(Path(path).read_bytes()) != digest for path, digest in native_pins.items()):
        _fail("native preservation producers changed during aggregate preparation")
    return result


def _reviewed_preservation_operation(graph, admission, args, kwargs, *, expected_graph_sha256,
        expected_admission_sha256, toolchain, instance_identity_profile=None, offered=None):
    import inspect
    _reviewed_source_use_profile(instance_identity_profile, version=2)
    owners = _reviewed_preservation_owners()
    graph_owner, admission_owner, _ = owners
    contracts.require_sha256(expected_graph_sha256, "expected_graph_sha256")
    contracts.require_sha256(expected_admission_sha256, "expected_admission_sha256")
    original = {"graph": graph, "admission": admission, "args": list(args), "kwargs": kwargs,
        "expected_graph_sha256": expected_graph_sha256, "expected_admission_sha256": expected_admission_sha256,
        "toolchain": toolchain}
    if instance_identity_profile is not None:
        original["instance_identity_profile"] = instance_identity_profile
    detached, commitment = admission_owner.norm._snapshot(original)
    offered_commitment = None
    if offered is not None:
        _, offered_commitment = admission_owner.norm._snapshot(_reviewed_preservation_offered(offered))
    pins = _reviewed_preservation_pins(owners)
    signature = inspect.signature(admission_owner.assess_reviewed_norm_admission_v2)
    bound = signature.bind(*detached["args"], **detached["kwargs"])
    if set(bound.arguments) != set(signature.parameters):
        _fail("complete reviewed admission replay inputs required for preservation")
    checked_graph = graph_owner.validate_reviewed_norm_graph_v2(detached["graph"], detached["admission"],
        *detached["args"], expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, **detached["kwargs"])
    if (admission_owner.norm._snapshot(original)[1] != commitment
            or admission_owner.norm._snapshot(detached)[1] != commitment):
        _fail("reviewed preservation inputs changed during admission and graph replay")
    result = _reviewed_preservation_project(checked_graph, detached["admission"], bound.arguments, owners,
        pins, commitment, expected_graph_sha256, expected_admission_sha256, toolchain,
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}))
    if offered is not None and result != offered:
        _fail("reviewed preservation differs from complete current regeneration")
    if (admission_owner.norm._snapshot(original)[1] != commitment
            or admission_owner.norm._snapshot(detached)[1] != commitment
            or _reviewed_preservation_pins(owners) != pins
            or (offered is not None and admission_owner.norm._snapshot(
                _reviewed_preservation_offered(offered))[1] != offered_commitment)):
        _fail("reviewed preservation inputs, preparation or producers changed during operation")
    _reviewed_source_use_profile(instance_identity_profile, version=2)
    return result


def prepare_reviewed_norm_preservation_corpus_v2(graph, admission, *args, expected_graph_sha256,
        expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
    """Replay all reviewed units and prepare unchanged independent H witnesses.

    This API performs no native build and grants no legal, corpus or training
    authority. Complete external source/review/dependency inputs remain required.
    Explicit reviewed-source-use/v1 binds each child to its replayed physical use.
    """
    return _reviewed_preservation_operation(graph, admission, args, kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, instance_identity_profile=instance_identity_profile)


def validate_reviewed_norm_preservation_corpus_v2(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        instance_identity_profile=None, **kwargs):
    """Regenerate every unit, obligation and companion under current admission.

    The preservation pin has its own name because expected_preparation_sha256
    remains the required, independently pinned admission replay keyword.
    """
    contracts.require_sha256(expected_preservation_sha256, "expected_preservation_sha256")
    if reviewed_preservation_corpus_sha256(preparation) != expected_preservation_sha256:
        _fail("independent complete reviewed preservation preparation pin differs")
    return _reviewed_preservation_operation(graph, admission, args, kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, instance_identity_profile=instance_identity_profile, offered=preparation)


__all__ += ["ReviewedPreservationCorpusPreparation", "REVIEWED_PRESERVATION_SCHEMA",
    "REVIEWED_PRESERVATION_PROFILE", "REVIEWED_SOURCE_USE_IDENTITY_PROFILE",
    "REVIEWED_SOURCE_USE_PRESERVATION_PROFILE", "prepare_reviewed_norm_preservation_corpus_v2",
    "validate_reviewed_norm_preservation_corpus_v2", "reviewed_preservation_corpus_sha256"]


REVIEWED_MIXED_PRESERVATION_SCHEMA = "legal-corpus-reviewed-preservation-preparation/v3"
REVIEWED_MIXED_PRESERVATION_PROFILE = "reviewed-multi-unit-mixed-relational-preservation/v3"
REVIEWED_MIXED_SOURCE_USE_PRESERVATION_PROFILE = REVIEWED_MIXED_PRESERVATION_PROFILE + "+reviewed-source-use/v1"
REVIEWED_MIXED_PRESERVATION_ROOT = "LegalReviewedMixedNormPreservation"
_REVIEWED_MIXED_PRESERVATION_LEAVES = (
    "mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
    "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering",
)


def _reviewed_mixed_preservation_policy():
    if ((REVIEWED_MIXED_PRESERVATION_SCHEMA, REVIEWED_MIXED_PRESERVATION_PROFILE,
            REVIEWED_MIXED_PRESERVATION_ROOT) != (
            "legal-corpus-reviewed-preservation-preparation/v3",
            "reviewed-multi-unit-mixed-relational-preservation/v3",
            "LegalReviewedMixedNormPreservation")
            or any(type(value) is not int for value in (MAX_REVIEWED_PRESERVATION_UNITS,
                MAX_REVIEWED_PRESERVATION_FILES, MAX_REVIEWED_PRESERVATION_MODULES,
                MAX_REVIEWED_PRESERVATION_OBLIGATIONS, joint_owner.MAX_PROJECT_BYTES))
            or (MAX_REVIEWED_PRESERVATION_UNITS, MAX_REVIEWED_PRESERVATION_FILES,
                MAX_REVIEWED_PRESERVATION_MODULES, MAX_REVIEWED_PRESERVATION_OBLIGATIONS,
                joint_owner.MAX_PROJECT_BYTES) != (8, 78, 11, 40, 8 * 1024 * 1024)):
        _fail("fixed reviewed mixed preservation domain and original bounds required")


def _reviewed_mixed_preservation_owners():
    from . import corpus_norm_definition_adapter, legal_reviewed_norm_admission_v3
    from . import legal_native_ast_preservation
    return corpus_norm_definition_adapter, legal_reviewed_norm_admission_v3, legal_native_ast_preservation


def _reviewed_mixed_preservation_child(native, profile, *, instance_identity_profile=None):
    """Select one closed child domain; never retag an Object or mixed value."""
    if profile == "authored-object-relational-deontic/v1":
        root, child_profile, family = ("LegalRelationalAstPreservation",
            "typed-relational-deontic-native-preservation/v1", "deontic_fol")
        if (native.RELATIONAL_PROJECT_ROOT != root or native.RELATIONAL_PROFILE != child_profile
                or _REVIEWED_PRESERVATION_LEAVES != (
                    "native_value_exact", "native_ast_closed", "denotation_matches_native",
                    "typed_source_lowering_exact", "role_denotation_matches_native")):
            _fail("fixed Object preservation policy changed")
        return (native.prepare_relational_ast_preservation, native.validate_relational_ast_preservation,
            root, child_profile + ("+reviewed-source-use/v1" if instance_identity_profile is not None else ""),
            family, "relational_report_sha256", _REVIEWED_PRESERVATION_LEAVES)
    if profile == "authored-many-sorted-relational-deontic/v1":
        root, child_profile, family = ("LegalMixedRelationalAstPreservation",
            "typed-many-sorted-relational-deontic-renderer-preservation/v1", "tdfol")
        if (native.MIXED_PROJECT_ROOT != root or native.MIXED_PROFILE != child_profile
                or _REVIEWED_MIXED_PRESERVATION_LEAVES != (
                    "mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
                    "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering")):
            _fail("fixed mixed renderer preservation policy changed")
        return (native.prepare_mixed_relational_ast_preservation,
            native.validate_mixed_relational_ast_preservation, root,
            child_profile + ("+reviewed-source-use/v1" if instance_identity_profile is not None else ""), family,
            "mixed_report_sha256", _REVIEWED_MIXED_PRESERVATION_LEAVES)
    _fail("explicit Object or mixed relational source profile required")


def _reviewed_mixed_preservation_project(graph, admission, replay, owners, pins, commitment,
        expected_graph_sha256, expected_admission_sha256, toolchain, *, instance_identity_profile=None):
    selected_profile = _reviewed_source_use_profile(instance_identity_profile, version=3)
    native = owners[2]
    authority, false_flags = dict(native.AUTHORITY), dict(native.FALSE_FLAGS)
    if (not authority or any(value is not False for value in authority.values())
            or not false_flags or any(value is not False for value in false_flags.values())):
        _fail("mixed aggregate preparation cannot confer authority")
    index, headers, predicates = _reviewed_preservation_units(graph, admission, replay, version=3)
    files, instance_modules, obligations, units, native_pins = {}, [], [], [], {}
    imports, common_profiles = {}, {}

    def add(name, body, *, shared=False):
        if type(name) is not str or type(body) is not str:
            _fail("ordinary mixed preservation project files required")
        if name in files:
            if shared and files[name] == body:
                return
            _fail("mixed preservation path or instance collision")
        if (len(files) >= MAX_REVIEWED_PRESERVATION_FILES
                or sum(len(text.encode("utf-8")) for text in files.values()) + len(body.encode("utf-8"))
                    > joint_owner.MAX_PROJECT_BYTES):
            _fail("complete mixed preservation aggregate exceeds original project bounds")
        files[name] = body

    for item in index:
        inputs = replay["preparation_inputs"]["relational_inputs"][item["unit_id"]]
        prepare, validate, root, profile, family, report_pin, leaves = _reviewed_mixed_preservation_child(
            native, item["relational_profile"], **({"instance_identity_profile": instance_identity_profile}
                if instance_identity_profile is not None else {}))
        child_args = dict(expected_report_sha256=item["relational_report_sha256"],
            expected_request_sha256=item["relational_request_sha256"], toolchain=toolchain)
        if instance_identity_profile is not None:
            child_args.update(_reviewed_source_use_child_args(item))
        child = prepare(inputs["report"], inputs["request_raw"], **child_args)
        child_sha = native.preparation_sha256(child)
        validate(child, inputs["report"], inputs["request_raw"],
            expected_preparation_sha256=child_sha, **child_args)
        manifest, child_files = child.to_dict(), dict(child.files)
        source_use = _reviewed_source_use_child_echo(manifest, item, child_args, instance_identity_profile)
        common = [root + ".Prelude", root + ".Semantics"]
        instances = [module for module in manifest["expected_modules"] if module not in [*common, root]]
        if (manifest["schema"] != native.SCHEMA or manifest["profile"] != profile
                or manifest["family"] != family or manifest["toolchain"] != toolchain
                or len(instances) != 1 or manifest[report_pin] != item["relational_report_sha256"]
                or manifest["original_request_sha256"] != item["relational_request_sha256"]
                or manifest["preparation_only"] is not True
                or type(manifest["training_mask"]) is not int or manifest["training_mask"] != 0
                or type(manifest["evaluation_gold_mask"]) is not int or manifest["evaluation_gold_mask"] != 0
                or set(manifest["authority"]) != set(authority)
                or any(value is not False for value in manifest["authority"].values())
                or any(manifest[key] is not False for key in false_flags)
                or native.AUTHORITY != authority or native.FALSE_FLAGS != false_flags):
            _fail("complete unchanged child preservation domain and false authorities required")
        if family == "tdfol":
            if (manifest["support_profile"]["sorts"] != ["Object", "EventFrame", "TimeFrame"]
                    or manifest["native_ast"] is not None
                    or manifest["native_TDFOL_route_used"] is not False
                    or manifest["native_parser_roundtrip"] is not False):
                _fail("mixed renderer child cannot acquire native AST or parser authority")
        elif (manifest["support_profile"]["typed_sort"] != "Object"
                or manifest["support_profile"]["native_sort"] is not None
                or manifest["support_profile"]["counting_supported"] is not False
                or manifest["support_profile"]["modal_agent"] is not None
                or manifest["support_profile"]["modal_context"] is not None):
            _fail("unchanged Object relational child contract required")
        instance = instances[0]
        if (re.fullmatch(re.escape(root) + r"\.Instance[0-9a-f]{64}", instance) is None
                or instance in instance_modules):
            _fail("distinct physical units require distinct unchanged child instances")
        theorems = [instance + "." + leaf for leaf in leaves]
        expected_imports = {common[0]: [], common[1]: [common[0]], instance: [common[1]], root: [instance]}
        expected_files = {module.replace(".", "/") + ".lean" for module in [*common, instance, root]}
        expected_files |= {"lakefile.toml", "lean-toolchain", "preservation-inputs.json"}
        if (manifest["expected_modules"] != [*common, instance, root]
                or manifest["module_imports"] != expected_imports or manifest["theorems"] != theorems
                or set(child_files) != expected_files or len(child.files) != 7
                or manifest["file_sha256"] != {name: _sha(body.encode("utf-8")) for name, body in child.files}
                or child_files["lean-toolchain"] != toolchain + "\n"
                or child_files[root + ".lean"] != "import " + instance + "\n"):
            _fail("all seven unchanged child files and five ordered domain obligations required")
        current_common = {"relational_profile": item["relational_profile"],
            "preservation_profile": profile, "family": family, "project_root": root,
            "modules": common, "theorem_suffixes": list(leaves)}
        if root in common_profiles and common_profiles[root] != current_common:
            _fail("child preservation namespace or theorem-domain collision")
        common_profiles[root] = current_common
        for path, digest in manifest["producer_pins"].items():
            if path in native_pins and native_pins[path] != digest:
                _fail("mixed aggregate child producer observations disagree")
            native_pins[path] = digest
        for module in [*common, instance]:
            add(module.replace(".", "/") + ".lean", child_files[module.replace(".", "/") + ".lean"],
                shared=module in common)
        prefix = "unit-companions/" + format(item["ordinal"], "02d") + "-"
        companions = []
        for ordinal, (name, body) in enumerate(child.files):
            target = prefix + "file-" + format(ordinal, "02d") + ".txt"
            add(target, body)
            companions.append({"original_path": name, "companion_path": target,
                "sha256": _sha(body.encode("utf-8"))})
        manifest_path = prefix + "manifest.json"
        add(manifest_path, child.manifest_json)
        units.append(dict(item, **source_use, child_preparation_sha256=child_sha,
            child_manifest_sha256=_sha(child.manifest_json.encode("utf-8")), child_manifest_path=manifest_path,
            original_child_files=companions, instance_module=instance, preservation_obligations=theorems,
            child_preservation_profile=profile, child_family=family))
        instance_modules.append(instance)
        obligations.extend(theorems)
        imports[instance] = [common[1]]
    common = [module for key in sorted(common_profiles) for module in common_profiles[key]["modules"]]
    root = REVIEWED_MIXED_PRESERVATION_ROOT
    if (len(set(obligations)) != 5 * len(index) or len(obligations) > MAX_REVIEWED_PRESERVATION_OBLIGATIONS
            or len(common) + len(instance_modules) + 1 > MAX_REVIEWED_PRESERVATION_MODULES):
        _fail("complete mixed population exceeds original module or obligation capacity; no unit omitted")
    add(root + ".lean", "".join("import " + module + "\n" for module in instance_modules))
    modules = [*common, *instance_modules, root]
    lake_roots = canonical_dag_json_bytes(modules).decode("utf-8")
    add("lakefile.toml", 'name = "legal_reviewed_mixed_norm_preservation"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ' + lake_roots + "\n")
    add("lean-toolchain", toolchain + "\n")
    bindings = {"schema": "legal-corpus-reviewed-preservation-bindings/v3",
        "input_commitment_sha256": commitment, "reviewed_graph_sha256": expected_graph_sha256,
        "reviewed_admission_sha256": expected_admission_sha256, "declaration_sha256": admission["declaration_sha256"],
        "definition_use_record_cids": [row["record_cid"] for row in graph["definition_use_records"]],
        "units": units}
    if instance_identity_profile is not None:
        bindings["instance_identity_profile"] = instance_identity_profile
    add("reviewed-input-bindings.json", canonical_dag_json_bytes(bindings).decode("utf-8") + "\n")
    for profile in common_profiles.values():
        first, second = profile["modules"]
        imports.update({first: [], second: [first]})
    imports[root] = instance_modules
    for path, digest in native_pins.items():
        if (path in pins and pins[path] != digest) or _sha(Path(path).read_bytes()) != digest:
            _fail("current mixed aggregate preservation producer differs")
    if native.AUTHORITY != authority or native.FALSE_FLAGS != false_flags:
        _fail("mixed aggregate false-authority policy changed during preparation")
    manifest = contracts.seal_record({**bindings,
        "schema": REVIEWED_MIXED_PRESERVATION_SCHEMA, "profile": selected_profile,
        "toolchain": toolchain, "target": "legal", "provenance_kind": admission["provenance_kind"],
        "scope_record_cid": graph["scope_record"]["record_cid"],
        "interpretation_record_cid": graph["interpretation_record"]["record_cid"],
        "signature_headers_by_unit": headers, "predicate_compatibility_ledger": predicates,
        "common_module_profiles": [common_profiles[key] for key in sorted(common_profiles)],
        "expected_modules": modules, "module_imports": imports, "preservation_obligations": obligations,
        "file_sha256": {name: _sha(body.encode("utf-8")) for name, body in sorted(files.items())},
        "producer_pins": pins, "native_producer_pins": native_pins,
        "support_profile": {"families": sorted({row["child_family"] for row in units}),
            "all_declared_units_required": True, "ordered_units_preserved": True,
            "complete_signature_headers_by_unit_retained": True,
            "signature_namespaces_are_exact_profile_and_header_commitments": True,
            "signature_symbol_subsets_may_differ_within_one_namespace": True,
            "overlapping_predicates_require_exact_signatures_and_ordered_roles_within_namespace": True,
            "cross_namespace_signature_or_carrier_coercion": False,
            "predicate_compatibility_is_syntactic_only": True,
            "cross_unit_definition_application_proved": False,
            "source_versions_may_differ_under_exact_common_reviewed_context": True,
            "duplicate_instance_declarations_across_physical_units": "entire_preparation_refused",
            "instance_rewriting_or_deduplication": False,
            "shared_files": "byte_identical_Prelude_and_Semantics_within_original_child_profile_only",
            "max_units": MAX_REVIEWED_PRESERVATION_UNITS, "max_files": MAX_REVIEWED_PRESERVATION_FILES,
            "max_modules": MAX_REVIEWED_PRESERVATION_MODULES, "max_obligations": MAX_REVIEWED_PRESERVATION_OBLIGATIONS,
            "max_project_utf8_bytes": joint_owner.MAX_PROJECT_BYTES},
        "trust_boundary": ["Complete current V3 reviewed admission, source and graph inputs are replayed.",
            "Every original child file and manifest and every active instance byte remains unchanged.",
            "Each unit retains its exact signature namespace and its own five child-profile obligations.",
            "Shared syntax is not shared legal meaning, a common model or cross-unit definition application.",
            "Capacity refusal preserves the entire input population; partitioning is a separate explicit operation.",
            "No alias premise, statutory truth, source-prose proof, corpus or release admission is supplied."],
        "preparation_only": True, "lean_compilation_status": "not_executed", "proof_status": "not_executed",
        "authority": authority, "semantic_use_eligible": False,
        "training_mask": 0, "evaluation_gold_mask": 0, **false_flags})
    result = ReviewedPreservationCorpusPreparation(canonical_dag_json_bytes(manifest).decode("utf-8"),
        tuple(sorted(files.items())))
    reviewed_preservation_corpus_sha256(result)
    if (native.AUTHORITY != authority or native.FALSE_FLAGS != false_flags
            or any(_sha(Path(path).read_bytes()) != digest for path, digest in native_pins.items())):
        _fail("mixed preservation producers changed during aggregate preparation")
    return result


def _reviewed_mixed_preservation_operation(graph, admission, args, kwargs, *, expected_graph_sha256,
        expected_admission_sha256, toolchain, instance_identity_profile=None, offered=None):
    import inspect
    _reviewed_source_use_profile(instance_identity_profile, version=3)
    _reviewed_mixed_preservation_policy()
    owners = _reviewed_mixed_preservation_owners()
    graph_owner, admission_owner, _ = owners
    contracts.require_sha256(expected_graph_sha256, "expected_graph_sha256")
    contracts.require_sha256(expected_admission_sha256, "expected_admission_sha256")
    original = {"graph": graph, "admission": admission, "args": list(args), "kwargs": kwargs,
        "expected_graph_sha256": expected_graph_sha256, "expected_admission_sha256": expected_admission_sha256,
        "toolchain": toolchain}
    if instance_identity_profile is not None:
        original["instance_identity_profile"] = instance_identity_profile
    detached, commitment = admission_owner.norm._snapshot(original)
    offered_commitment = None
    if offered is not None:
        _, offered_commitment = admission_owner.norm._snapshot(_reviewed_preservation_offered(offered))
    pins = _reviewed_preservation_pins(owners)
    signature = inspect.signature(admission_owner.assess_reviewed_norm_admission_v3)
    bound = signature.bind(*detached["args"], **detached["kwargs"])
    if set(bound.arguments) != set(signature.parameters):
        _fail("complete original V3 reviewed admission replay inputs required")
    checked_graph = graph_owner.validate_reviewed_norm_graph_v3(detached["graph"], detached["admission"],
        *detached["args"], expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, **detached["kwargs"])
    if (admission_owner.norm._snapshot(original)[1] != commitment
            or admission_owner.norm._snapshot(detached)[1] != commitment):
        _fail("mixed preservation inputs changed during complete reviewed graph replay")
    result = _reviewed_mixed_preservation_project(checked_graph, detached["admission"], bound.arguments,
        owners, pins, commitment, expected_graph_sha256, expected_admission_sha256, toolchain,
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}))
    if offered is not None and result != offered:
        _fail("mixed reviewed preservation differs from complete current regeneration")
    if (admission_owner.norm._snapshot(original)[1] != commitment
            or admission_owner.norm._snapshot(detached)[1] != commitment
            or _reviewed_preservation_pins(owners) != pins
            or (offered is not None and admission_owner.norm._snapshot(
                _reviewed_preservation_offered(offered))[1] != offered_commitment)):
        _fail("mixed preservation inputs, project or producer changed during operation")
    _reviewed_source_use_profile(instance_identity_profile, version=3)
    _reviewed_mixed_preservation_policy()
    return result


def prepare_reviewed_norm_preservation_corpus_v3(graph, admission, *args, expected_graph_sha256,
        expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
    """Replay every V3 unit; optionally bind children to explicit reviewed source uses."""
    return _reviewed_mixed_preservation_operation(graph, admission, args, kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, instance_identity_profile=instance_identity_profile)


def validate_reviewed_norm_preservation_corpus_v3(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        instance_identity_profile=None, **kwargs):
    """Regenerate the complete V3 project without coercion, clipping or authority."""
    contracts.require_sha256(expected_preservation_sha256, "expected_preservation_sha256")
    if reviewed_preservation_corpus_sha256(preparation) != expected_preservation_sha256:
        _fail("independent complete mixed preservation preparation pin differs")
    return _reviewed_mixed_preservation_operation(graph, admission, args, kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, instance_identity_profile=instance_identity_profile, offered=preparation)


__all__ += ["REVIEWED_MIXED_PRESERVATION_SCHEMA", "REVIEWED_MIXED_PRESERVATION_PROFILE",
    "REVIEWED_MIXED_SOURCE_USE_PRESERVATION_PROFILE",
    "REVIEWED_MIXED_PRESERVATION_ROOT", "prepare_reviewed_norm_preservation_corpus_v3",
    "validate_reviewed_norm_preservation_corpus_v3"]


# This explicit profile constructs a model for one reviewed unary definition.
# It does not change the independent V2/V3 preservation profiles or their files.
REVIEWED_DEFINITION_REALIZATION_SCHEMA = "legal-reviewed-definition-realization-preparation/v1"
REVIEWED_DEFINITION_REALIZATION_PROFILE = "reviewed-unary-object-definition-realization/v1"
REVIEWED_DEFINITION_REALIZATION_ROOT = "LegalReviewedDefinitionRealization"


def _reviewed_definition_realization_profile(instance_identity_profile, *, definition_application_profile=None):
    """Select the caller's realization identity domain without reading artifacts."""
    _reviewed_definition_application_kwargs(definition_application_profile)
    _reviewed_source_use_profile(instance_identity_profile, version=3)
    profile = (REVIEWED_DEFINITION_REALIZATION_PROFILE if instance_identity_profile is None else
        REVIEWED_DEFINITION_REALIZATION_PROFILE + "+reviewed-source-use/v1")

    return profile if definition_application_profile is None else profile + "+whole-norm-definition-expansion/v1"

def _reviewed_definition_realization_policy(*, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_definition_realization_profile(instance_identity_profile, **_reviewed_definition_application_kwargs(definition_application_profile))
    _reviewed_mixed_preservation_policy()
    if (REVIEWED_DEFINITION_REALIZATION_SCHEMA, REVIEWED_DEFINITION_REALIZATION_PROFILE,
            REVIEWED_DEFINITION_REALIZATION_ROOT) != (
            "legal-reviewed-definition-realization-preparation/v1",
            "reviewed-unary-object-definition-realization/v1", "LegalReviewedDefinitionRealization"):
        _fail("fixed explicit reviewed definition realization profile required")


def _reviewed_definition_realization_selection(graph, admission, replay, upstream, native, *, instance_identity_profile=None, physical_context=None):
    """Select exact already reviewed nodes; never parse a second legal language."""
    _reviewed_definition_realization_profile(instance_identity_profile)
    declaration = replay["preparation_inputs"]["declaration"]
    index, _, _ = _reviewed_preservation_units(graph, admission, replay, version=3)
    definitions = [row for row in index if row["kind"] == "definition"]
    if len(definitions) != 1 or (physical_context is None and declaration["cross_references"]):
        _fail("initial realization requires one complete definition and no external dependency declarations")
    if physical_context is not None and physical_context["cross_references"] != declaration["cross_references"]:
        _fail("physical evidence dependencies differ from the complete reviewed declaration")
    definition = definitions[0]
    if definition["relational_profile"] != "authored-object-relational-deontic/v1":
        _fail("initial realized definition requires the original unary Object profile")
    by_id = {row["unit_id"]: row for row in admission["units"]}
    ir = by_id[definition["unit_id"]]["canonical_ir"]
    root = ir["typed_expression"]["root"]
    if (root["kind"] != "forall" or len(root["binders"]) != 1 or len(root["arguments"]) != 1
            or root["binders"][0]["sort"]["name"] != "Object"):
        _fail("one complete universal Object definition binder required")
    binder = root["binders"][0]
    equivalence = root["arguments"][0]
    if equivalence["kind"] != "iff" or len(equivalence["arguments"]) != 2:
        _fail("complete forward head/body definition equivalence required")
    head, body = equivalence["arguments"]
    if (head["kind"] != "predicate" or len(head["arguments"]) != 1
            or head["arguments"][0]["kind"] != "variable"
            or head["arguments"][0]["symbol"] != binder["name"]
            or head["arguments"][0]["sort"] != binder["sort"]):
        _fail("selected unary definition head must use its exact Object binder")
    symbol = head["symbol"]
    roles = {row["symbol"]: row["roles"] for row in ir["argument_roles"]}
    if symbol not in roles or len(roles[symbol]) != 1:
        _fail("exact unary definition head role required")
    body_count = 0

    def body_fragment(node, depth=0):
        nonlocal body_count
        body_count += 1
        if body_count > 4096 or depth > 64:
            _fail("complete definition body exceeds original unary fragment bounds")
        kind = node["kind"]
        if kind == "predicate":
            if (node["symbol"] == symbol or len(node["arguments"]) != 1
                    or node["symbol"] not in roles or len(roles[node["symbol"]]) != 1
                    or node["arguments"][0]["kind"] != "variable"
                    or node["arguments"][0]["symbol"] != binder["name"]
                    or node["arguments"][0]["sort"] != binder["sort"]):
                _fail("nonrecursive exact unary Object body atoms required")
        elif kind in ("and", "or", "not"):
            if len(node["arguments"]) != (1 if kind == "not" else 2):
                _fail("complete ordered unary Boolean definition body required")
            for child in node["arguments"]:
                body_fragment(child, depth + 1)
        else:
            _fail("quantified, modal, counted or other definition bodies require a separate realization profile")
    body_fragment(body)
    units = upstream["units"]
    if [row["unit_id"] for row in units] != [row["unit_id"] for row in index]:
        _fail("realization must retain every ordered original V3 preservation unit")
    source_use_bindings = []
    for item, unit in zip(index, units, strict=True):
        if any(unit.get(key) != value for key, value in item.items()):
            _fail("realization unit differs from complete current source/graph replay")
        if instance_identity_profile is not None:
            expected = _reviewed_source_use_child_args(item)
            if (unit.get("source_use_binding") != expected["source_use_binding"]
                    or unit.get("source_use_binding_sha256") != expected["expected_source_use_binding_sha256"]):
                _fail("realization requires each exact replay-derived physical source-use binding")
            source_use_bindings.append({"unit_id": item["unit_id"],
                "source_use_binding": expected["source_use_binding"],
                "source_use_binding_sha256": expected["expected_source_use_binding_sha256"]})
        elif any(key in unit for key in ("source_use_binding", "source_use_binding_sha256")):
            _fail("legacy realization cannot consume source-use unit identities")
    modules = {row["unit_id"]: row["instance_module"] for row in units}
    uses = declaration["definition_uses"]
    selected, occurrence_rows = [], []
    for use in uses:
        if use["definition_unit_id"] != definition["unit_id"] or use["defined_predicate"] != symbol:
            _fail("one exact selected governing definition must cover every reviewed norm")
        target = by_id[use["use_unit_id"]]["canonical_ir"]
        target_roles = {row["symbol"]: row["roles"] for row in target["argument_roles"]}
        if target_roles.get(symbol) != roles[symbol]:
            _fail("realization head ordered role differs from selected definition")
        found = []

        def visit(node, path, binders, modal_depth):
            kind = node["kind"]
            nested = binders
            if kind in ("forall", "exists"):
                if len(node["binders"]) != 1:
                    _fail("single original nonshadowing binder required")
                nested = [*binders, {"typed_path": path, "quantifier": kind, **node["binders"][0]}]
            if kind == "predicate" and node["symbol"] == symbol:
                argument = node["arguments"][0] if len(node["arguments"]) == 1 else None
                matches = [row for row in binders if argument is not None and row["name"] == argument["symbol"]]
                if (modal_depth or argument is None or argument["kind"] != "variable"
                        or argument["sort"] != binder["sort"] or len(matches) != 1
                        or matches[0]["sort"] != argument["sort"]):
                    _fail("exact Object head occurrence outside opaque modalities required")
                found.append({"typed_path": path, "typed_node": node, "argument": argument,
                    "binders": list(binders), "ordered_roles": list(roles[symbol])})
            for ordinal, child in enumerate(node["arguments"]):
                visit(child, path + "/arguments/" + str(ordinal), nested, modal_depth)
            if kind == "extension":
                for ordinal, child in enumerate(node["extension"]["children"]):
                    visit(child, path + "/extension/children/" + str(ordinal), nested, modal_depth + 1)
        visit(target["typed_expression"]["root"], "/root", [], 0)
        if [row["typed_path"] for row in found] != use["target_typed_paths"] or not found:
            _fail("complete ordered every-use head occurrence population required")
        graph_uses = [row for row in graph["definition_use_records"]
                      if row["definition_unit_id"] == use["definition_unit_id"]
                      and row["use_unit_id"] == use["use_unit_id"]]
        if len(graph_uses) != 1:
            _fail("one exact reviewed graph record required for each distinct physical use")
        for row in found:
            occurrence_rows.append({"ordinal": len(occurrence_rows), "unit_id": use["use_unit_id"],
                "instance_module": modules[use["use_unit_id"]],
                "relational_profile": by_id[use["use_unit_id"]]["relational_profile"],
                "definition_use_record_cid": graph_uses[0]["record_cid"],
                "source_occurrence_cid": use["use_occurrence_cid"], **row})
        selected.append(use["use_unit_id"])
    if (len(set(selected)) != len(selected)
            or set(selected) != {row["unit_id"] for row in index if row["kind"] == "norm"}):
        _fail("every complete distinct norm unit requires its own reviewed governing use")
    selection = {"definition_unit_id": definition["unit_id"], "definition_instance_module": modules[definition["unit_id"]],
        "definition_source_occurrence_cid": definition["source_occurrence_cid"],
        "definition_ir_sha256": definition["complete_ir_sha256"], "head_symbol": symbol,
        "head_roles": roles[symbol], "definition_binder": binder,
        "body_typed_path": "/root/arguments/0/arguments/1", "body_typed_node": body,
        "body_typed_sha256": _sha(canonical_dag_json_bytes(body)),
        "body_role_ast": native._relational_source_syntax(body, roles),
        "head_role_ast": native._relational_source_syntax(head, roles),
        "definition_use_records": graph["definition_use_records"], "occurrences": occurrence_rows}

    if instance_identity_profile is not None:
        selection.update(instance_identity_profile=instance_identity_profile, source_use_bindings=source_use_bindings)
    return selection

def _reviewed_definition_realization_lean(selection, units, native, module):
    """Construct explicit atom models; no Iff premise or opaque modal rewrite."""
    obj, mixed = "LegalRelationalAstPreservation", "LegalMixedRelationalAstPreservation"
    q = native._string
    head, role = q(selection["head_symbol"]), q(selection["head_roles"][0])
    binder = q(selection["definition_binder"]["name"])
    obj_atoms = "String → List (String × Object) → Nat → Prop"
    mix_type = mixed + ".MixedEntity Object EventFrame TimeFrame"
    mix_atoms = "String → List (String × (" + mix_type + ")) → Nat → Prop"
    obj_parameters = "{Object Agent : Type} (base : " + obj + ".Interpretation Object Agent) (atoms : " + obj_atoms + ")"
    mix_parameters = ("{Object Agent EventFrame TimeFrame : Type} (base : " + obj + ".Interpretation Object Agent) "
        "(atoms : " + obj_atoms + ") (mixedBase : " + mixed + ".Interpretation (" + mix_type + ") Unit) "
        "(mixedAtoms : " + mix_atoms + ")")
    body = ("namespace " + module + "\n"
        + "def definitionBodyAst : " + obj + ".RoleFormula := " + selection["body_role_ast"] + "\n"
        + "def bodyAt " + obj_parameters + " (entity : Object) (t : Nat) : Prop :=\n"
        + "  " + obj + ".roleDenote base atoms definitionBodyAst (" + obj + ".updateEnvironment "
        + obj + ".emptyEnvironment " + binder + " entity) t\n"
        + "def realizedObjectAtoms " + obj_parameters + " (name : String) (values : List (String × Object)) (t : Nat) : Prop :=\n"
        + "  if name = " + head + " then\n"
        + "    List.casesOn (motive := fun _ => Prop) values False (fun pair rest =>\n"
        + "      List.casesOn (motive := fun _ => Prop) rest\n"
        + "        (Prod.casesOn (motive := fun _ => Prop) pair (fun label entity =>\n"
        + "          if label = " + role + " then bodyAt base atoms entity t else False))\n"
        + "        (fun _ _ => False))\n"
        + "  else atoms name values t\n")
    if any(unit["child_family"] == "tdfol" for unit in units):
        body += ("def realizedMixedAtoms {Object Agent EventFrame TimeFrame : Type}\n"
        + "    (base : " + obj + ".Interpretation Object Agent) (atoms : " + obj_atoms + ")\n"
        + "    (mixedAtoms : " + mix_atoms + ") (name : String)\n"
        + "    (values : List (String × (" + mix_type + "))) (t : Nat) : Prop :=\n"
        + "  if name = " + head + " then\n"
        + "    List.casesOn (motive := fun _ => Prop) values False (fun pair rest =>\n"
        + "      List.casesOn (motive := fun _ => Prop) rest\n"
        + "        (Prod.casesOn (motive := fun _ => Prop) pair (fun label value =>\n"
        + "          Sum.casesOn (motive := fun _ => Prop) value (fun _ => False) (fun objectOrEvent =>\n"
        + "            Sum.casesOn (motive := fun _ => Prop) objectOrEvent\n"
        + "              (fun entity => if label = " + role + " then bodyAt base atoms entity t else False)\n"
        + "              (fun _ => False))))\n"
        + "        (fun _ _ => False))\n"
        + "  else mixedAtoms name values t\n")
    # Logical child projection is independent of atom rendering.  Every use
    # witness is tied to the ORIGINAL complete child AST at its reviewed path.
    for prefix, type_name, constructors, enabled in (
            ("object", obj + ".RoleFormula", (
                ("negation", "body", None), ("conjunction", "left right", None),
                ("disjunction", "left right", None), ("implication", "left right", None),
                ("equivalence", "left right", None), ("universal", "_ body", None),
                ("existential", "_ body", None), ("modal", "_ body", None)), True),
            ("mixed", mixed + ".MixedFormula", (
                ("negation", "_ body", None), ("conjunction", "_ left right", None),
                ("disjunction", "_ left right", None), ("implication", "_ left right", None),
                ("equivalence", "_ left right", None), ("universal", "_ _ _ body", None),
                ("existential", "_ _ _ body", None), ("modal", "_ _ _ body", None)),
                any(unit["child_family"] == "tdfol" for unit in units))):
        if not enabled:
            continue
        # Explicit recursors keep the source projection constructive without
        # equation-compiler recursion over a changing source accumulator.
        body += ("def " + prefix + "FormulaChild (source : " + type_name + ") (index : Nat) : Option " + type_name + " :=\n"
            + "  " + type_name + ".casesOn (motive := fun _ => Option " + type_name + ") source\n"
            + "    (fun _ _ _ => none)\n")
        if prefix == "mixed":
            body += "    (fun _ _ _ => none)\n"
        for constructor, fields, _ in constructors:
            if "left right" in fields:
                branch = "Nat.casesOn index (some left) (fun rest => Nat.casesOn rest (some right) (fun _ => none))"
            else:
                branch = "Nat.casesOn index (some body) (fun _ => none)"
            body += "    (fun " + fields + " => " + branch + ")\n"
        body += ("noncomputable def " + prefix + "FormulaAt (source : " + type_name + ") (path : List Nat) : Option " + type_name + " :=\n"
            + "  List.rec (motive := fun _ => " + type_name + " → Option " + type_name + ")\n"
            + "    (fun node => some node)\n"
            + "    (fun index _ descend node =>\n"
            + "      Option.casesOn (motive := fun _ => Option " + type_name + ") (" + prefix + "FormulaChild node index)\n"
            + "        none (fun child => descend child)) path source\n")
    theorems, entries = [], []

    def theorem(name, statement, proof, binding):
        nonlocal body
        body += "theorem " + name + " " + statement + " := by\n" + proof + "\n#print axioms " + name + "\n"
        qualified = module + "." + name
        theorems.append(qualified)
        entries.append({"theorem": qualified, "binding": binding, "declaration": "theorem " + name + " " + statement})

    definition_module = selection["definition_instance_module"]
    source_ast = "(.universal " + binder + " (.equivalence " + selection["head_role_ast"] + " definitionBodyAst))"
    theorem("definition_body_source_exact", ": " + definition_module + ".typedSourceAst = " + source_ast,
        "  rfl", {"kind": "exact_definition_body_subtree", "body_typed_sha256": selection["body_typed_sha256"]})
    interpreted = "(" + obj + ".roleInterpretation base (realizedObjectAtoms base atoms) " + definition_module + ".predicateRoles)"
    theorem("definition_realized", obj_parameters + " (t : Nat) : " + definition_module + ".formula_0 " + interpreted + " t",
        "  apply (" + definition_module + ".role_denotation_matches_native base (realizedObjectAtoms base atoms) t).mp\n"
        + "  intro entity\n  exact Iff.intro (fun h => h) (fun h => h)",
        {"kind": "constructed_definition_model", "definition_unit_id": selection["definition_unit_id"],
         "desired_equivalence_hypothesis": False})
    for occurrence in selection["occurrences"]:
        number = str(occurrence["ordinal"])
        is_mixed = occurrence["relational_profile"] == "authored-many-sorted-relational-deontic/v1"
        names, declarations, environment = {}, [], (mixed + ".emptyCountedEnvironment" if is_mixed else obj + ".emptyEnvironment")
        for ordinal, binding in enumerate(occurrence["binders"]):
            name, sort, local = binding["name"], binding["sort"]["name"], "bound" + str(ordinal)
            if sort not in ("Object", "EventFrame", "TimeFrame") or (not is_mixed and sort != "Object"):
                _fail("realization occurrence has an unsupported binder carrier")
            names[name] = local
            declarations.append("(" + local + " : " + sort + ")")
            update = (mixed + ".updateCounted" + {"Object": "Object", "EventFrame": "Event", "TimeFrame": "Time"}[sort]
                      if is_mixed else obj + ".updateEnvironment")
            environment = "(" + update + " " + environment + " " + q(name) + " " + local + ")"
        argument = occurrence["argument"]
        if argument["symbol"] not in names:
            _fail("head occurrence must bind an actual original entity valuation")
        if is_mixed:
            atom = occurrence["typed_node"]
            ast = "(.predicate " + q(atom["node_id"]) + " " + head + " [⟨" + q(argument["node_id"]) + ", " + q(argument["symbol"]) + ", .object⟩])"
            body += "def occurrenceAst" + number + " : " + mixed + ".MixedFormula := " + ast + "\n"
            left = (mixed + ".mixedRoleDenote mixedBase (realizedMixedAtoms base atoms mixedAtoms) "
                + occurrence["instance_module"] + ".mixedArgumentRoles occurrenceAst" + number + " " + environment + " t")
        else:
            ast = native._relational_source_syntax(occurrence["typed_node"], {selection["head_symbol"]: selection["head_roles"]})
            body += "def occurrenceAst" + number + " : " + obj + ".RoleFormula := " + ast + "\n"
            left = obj + ".roleDenote base (realizedObjectAtoms base atoms) occurrenceAst" + number + " " + environment + " t"
        tokens = occurrence["typed_path"].split("/")
        if (tokens[:2] != ["", "root"] or (len(tokens) - 2) % 2
                or any(tokens[offset] != "arguments" or tokens[offset + 1] not in ("0", "1")
                       for offset in range(2, len(tokens), 2))):
            _fail("exact original nonmodal logical-child source path required")
        indices = [int(tokens[offset]) for offset in range(3, len(tokens), 2)]
        projection = "[" + ", ".join(str(index) for index in indices) + "]"
        source_ast = occurrence["instance_module"] + (".typedMixedAst" if is_mixed else ".typedSourceAst")
        theorem("occurrence_" + number + "_source_exact", ": " + ("mixed" if is_mixed else "object")
            + "FormulaAt " + source_ast + " " + projection + " = some occurrenceAst" + number,
            "  rfl", {"kind": "exact_original_occurrence_subtree", "unit_id": occurrence["unit_id"],
                "source_typed_path": occurrence["typed_path"], "logical_child_indices": indices,
                "definition_use_record_cid": occurrence["definition_use_record_cid"]})
        statement = (mix_parameters if is_mixed else obj_parameters) + " " + " ".join(declarations) + " (t : Nat) :\n    " + left + " ↔ bodyAt base atoms " + names[argument["symbol"]] + " t"
        theorem("occurrence_" + number + "_matches_body", statement, "  exact Iff.intro (fun h => h) (fun h => h)",
            {"kind": "exact_reviewed_head_occurrence", **occurrence})
    for ordinal, unit in enumerate(units):
        name, instance = "unit_" + str(ordinal) + "_preservation_under_realization", unit["instance_module"]
        if unit["child_family"] == "tdfol":
            atom_function = "(realizedMixedAtoms base atoms mixedAtoms)"
            statement = (mix_parameters + " (t : Nat) :\n    " + mixed + ".mixedRoleDenote mixedBase " + atom_function
                + " " + instance + ".mixedArgumentRoles " + instance + ".typedMixedAst " + mixed + ".emptyCountedEnvironment t ↔\n      "
                + instance + ".formula (" + mixed + ".mixedRoleInterpretation mixedBase " + atom_function + " " + instance + ".mixedArgumentRoles) t")
            proof = "  exact @" + instance + ".mixed_role_denotation_matches_lowering Object EventFrame TimeFrame mixedBase " + atom_function + " t"
        else:
            atom_function = "(realizedObjectAtoms base atoms)"
            statement = (obj_parameters + " (t : Nat) :\n    " + obj + ".roleDenote base " + atom_function
                + " " + instance + ".typedSourceAst " + obj + ".emptyEnvironment t ↔\n      " + instance + ".formula_0 ("
                + obj + ".roleInterpretation base " + atom_function + " " + instance + ".predicateRoles) t")
            proof = "  exact @" + instance + ".role_denotation_matches_native Object Agent base " + atom_function + " t"
        theorem(name, statement, proof, {"kind": "unchanged_child_preservation_instantiation", "unit_id": unit["unit_id"],
            "instance_module": instance, "child_preservation_sha256": unit["child_preparation_sha256"]})
    body += "end " + module + "\n"
    return body, theorems, entries


def _reviewed_definition_realization_project(preservation, graph, admission, replay, owners, pins,
        commitment, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, *,
        instance_identity_profile=None, definition_application_profile=None,
        physical_context=None, physical_context_owner_sha256=None, physical_bridge_version=1):
    profile = _reviewed_definition_realization_profile(instance_identity_profile, **_reviewed_definition_application_kwargs(definition_application_profile))
    if physical_context is not None:
        if physical_bridge_version == 2:
            _reviewed_physical_realization_policy_v2()
            _reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile)
            profile = REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2
        else:
            if instance_identity_profile is not None or definition_application_profile is not None:
                _fail("physical realization selected profiles require a separately closed bridge")
            profile = REVIEWED_PHYSICAL_REALIZATION_PROFILE
    native = owners[2]
    manifest, files = preservation.to_dict(), dict(preservation.files)
    if (manifest["schema"] != REVIEWED_MIXED_PRESERVATION_SCHEMA
            or manifest["profile"] != _reviewed_source_use_profile(instance_identity_profile, version=3)
            or manifest["support_profile"]["cross_unit_definition_application_proved"] is not False):
        _fail("unchanged current V3 preservation profile required before realization")
    selection = _reviewed_definition_realization_selection(graph, admission, replay, manifest, native,
        **({"physical_context": physical_context} if physical_context is not None else {}),
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}))
    identity_input = {"profile": profile,
        "upstream_preservation_sha256": expected_preservation_sha256, "selection": selection}
    physical_binding = {} if physical_context is None else {
        "physical_context": physical_context, "physical_context_owner_sha256": physical_context_owner_sha256,
        "physical_context_sha256": _sha(canonical_dag_json_bytes(physical_context))}
    if physical_context is not None and physical_bridge_version == 2:
        physical_binding["physical_bridge_version"] = 2
    if physical_context is not None:
        identity_input.update(physical_context_sha256=physical_binding["physical_context_sha256"],
            physical_context_owner_sha256=physical_context_owner_sha256)
    applications = None
    if definition_application_profile is not None:
        applications = _reviewed_definition_application_prepare_rows(selection, manifest["units"], admission,
            definition_application_profile)
        identity_input["definition_applications"] = applications
    identity = _sha(canonical_dag_json_bytes(identity_input))
    module = REVIEWED_DEFINITION_REALIZATION_ROOT + ".Instance" + identity
    source, additions, theorem_bindings = _reviewed_definition_realization_lean(selection, manifest["units"], native, module)
    application_obligations = []
    if applications is not None:
        application_source, application_obligations, application_bindings = _reviewed_definition_application_lean(
            selection, manifest["units"], applications, native, module)
        ending = "end " + module + "\n"
        if not source.endswith(ending):
            _fail("exact original realization namespace closing required")
        source = source[:-len(ending)] + application_source + ending
        additions = [*additions, *application_obligations]
        theorem_bindings = [*theorem_bindings, *application_bindings]
    original_files = dict(files)
    module_path = module.replace(".", "/") + ".lean"
    root = REVIEWED_DEFINITION_REALIZATION_ROOT
    root_path = root + ".lean"
    bindings_path = "definition-realization-input-bindings.json"
    companion_lake = "definition-realization-original-lakefile.txt"
    if any(name in files for name in (module_path, root_path, bindings_path, companion_lake)):
        _fail("realization file or namespace collision")
    modules = [*manifest["expected_modules"], module, root]
    obligations = [*manifest["preservation_obligations"], *additions]
    if (len(modules) > MAX_REVIEWED_PRESERVATION_MODULES or len(set(modules)) != len(modules)
            or len(obligations) > MAX_REVIEWED_PRESERVATION_OBLIGATIONS
            or len(set(obligations)) != len(obligations)):
        _fail("complete realization population exceeds original modules or obligations; no unit omitted")
    files[module_path] = "".join("import " + row["instance_module"] + "\n" for row in manifest["units"]) + source
    files[root_path] = "import " + REVIEWED_MIXED_PRESERVATION_ROOT + "\nimport " + module + "\n"
    files[companion_lake] = files["lakefile.toml"]
    files["lakefile.toml"] = ('name = "legal_reviewed_definition_realization"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = '
        + canonical_dag_json_bytes(modules).decode("utf-8") + "\n")
    bindings = {"schema": "legal-reviewed-definition-realization-bindings/v1",
        "input_commitment_sha256": commitment, "reviewed_preservation_sha256": expected_preservation_sha256,
        "reviewed_graph_sha256": expected_graph_sha256, "reviewed_admission_sha256": expected_admission_sha256,
        "declaration_sha256": admission["declaration_sha256"], "selection": selection,
        "upstream_manifest": manifest, "original_file_sha256": manifest["file_sha256"],
        "theorem_bindings": theorem_bindings, **physical_binding}
    if instance_identity_profile is not None:
        bindings["instance_identity_profile"] = instance_identity_profile
    if applications is not None:
        bindings.update(definition_application_profile=definition_application_profile,
            definition_applications=applications, definition_application_obligations=application_obligations)
    files[bindings_path] = canonical_dag_json_bytes(bindings).decode("utf-8") + "\n"
    if (len(files) > MAX_REVIEWED_PRESERVATION_FILES
            or sum(len(value.encode("utf-8")) for value in files.values()) > joint_owner.MAX_PROJECT_BYTES):
        _fail("complete realization project exceeds original files or byte bound; no input truncated")
    if any(files[name] != value for name, value in original_files.items() if name != "lakefile.toml"):
        _fail("realization cannot rewrite any original V3 child, root, binding or companion")
    imports = {**manifest["module_imports"], module: [row["instance_module"] for row in manifest["units"]],
        root: [REVIEWED_MIXED_PRESERVATION_ROOT, module]}
    result_manifest = contracts.seal_record({**bindings,
        "schema": (REVIEWED_DEFINITION_REALIZATION_SCHEMA if physical_context is None else
            REVIEWED_PHYSICAL_REALIZATION_SCHEMA_V2 if physical_bridge_version == 2 else REVIEWED_PHYSICAL_REALIZATION_SCHEMA), "profile": profile,
        "toolchain": toolchain, "target": "legal", "expected_modules": modules, "module_imports": imports,
        "units": manifest["units"], "preservation_obligations": obligations,
        "realization_obligations": additions, "file_sha256": {name: _sha(value.encode("utf-8")) for name, value in sorted(files.items())},
        "producer_pins": pins, "native_producer_pins": manifest["native_producer_pins"],
        "support_profile": {"single_unary_Object_definition": True, "nonrecursive_boolean_body": True,
            "all_original_V3_units_and_children_retained": True, "explicit_common_Object_carrier": True,
            "mixed_Object_injection": "Sum.inr(Sum.inl entity)", "implicit_namespace_coercion": False,
            "single_binder_quantifier_nodes_only": True,
            "head_occurrences_under_modalities_supported": False, "opaque_modal_rewrite": False,
            "cross_unit_definition_application_proved": False,
            "max_units": MAX_REVIEWED_PRESERVATION_UNITS, "max_files": MAX_REVIEWED_PRESERVATION_FILES,
            "max_modules": MAX_REVIEWED_PRESERVATION_MODULES, "max_obligations": MAX_REVIEWED_PRESERVATION_OBLIGATIONS,
            "max_project_utf8_bytes": joint_owner.MAX_PROJECT_BYTES,
            **({"conditional_whole_norm_obligations": True, "source_definition_premise_required": True,
                "original_atom_interpretations_unchanged": True} if applications is not None else {})},
        "trust_boundary": ["Complete current V3 source, review, graph, dependency and child preservation inputs are replayed.",
            ("Only constructed role-atom interpretations realize the independently denoted definition body; arbitrary original interpretations are not equated."
             if applications is None else
             "Old constructed-model obligations remain; new whole-norm expansion obligations require satisfaction of the exact original independently denoted SOURCE definition under unchanged arbitrary original atom interpretations. Mixed source-definition evaluation uses the canonical Object restriction of the same mixed atoms. No source-definition truth, unconditional arbitrary-model equivalence, legal applicability/meaning, corpus, training or release authority is supplied."),
            "Definition realization supplies no actual category membership, norm truth, compliance, legal meaning or statutory/source theorem.",
            "Only single-binder quantifier nodes are supported; unsupported nodes refuse the entire population rather than collapsing binder scope.",
            "Ambient Nat evaluation time stays distinct from legal applicability dates and the authored TimeFrame carrier.",
            "Original modal fields and complete original child sources are unchanged; no opaque modal replacement or extra axiom is supplied.",
            "The generated new obligations are unexecuted; no native/proof/cache/corpus/learning admission follows from preparation."],
        "preparation_only": True, "lean_compilation_status": "not_executed", "proof_status": "not_executed",
        "authority": dict(native.AUTHORITY), "semantic_use_eligible": False,
        "training_mask": 0, "evaluation_gold_mask": 0, **dict(native.FALSE_FLAGS)})
    result = ReviewedPreservationCorpusPreparation(canonical_dag_json_bytes(result_manifest).decode("utf-8"), tuple(sorted(files.items())))
    reviewed_preservation_corpus_sha256(result)
    return result


def _reviewed_definition_realization_callbacks(owners, *, definition_application_profile=None):
    native = owners[2]
    functions = (_reviewed_definition_realization_policy, _reviewed_definition_realization_profile,
        _reviewed_definition_application_kwargs, _reviewed_definition_application_pins,
        _reviewed_source_use_profile, _reviewed_source_use_child_args, _reviewed_mixed_preservation_policy,
        _reviewed_definition_realization_selection,
        _reviewed_definition_realization_lean, _reviewed_definition_realization_project,
        _reviewed_definition_realization_callbacks, _reviewed_definition_realization_operation,
        prepare_reviewed_definition_realization_corpus_v1, validate_reviewed_definition_realization_corpus_v1,
        validate_reviewed_norm_preservation_corpus_v3, _reviewed_mixed_preservation_operation,
        _reviewed_mixed_preservation_project, _reviewed_preservation_units, _reviewed_preservation_pins,
        _reviewed_preservation_offered, reviewed_preservation_corpus_sha256, canonical_dag_json_bytes,
        _reviewed_mixed_preservation_owners, _sha, _fail, ReviewedPreservationCorpusPreparation,
        owners[1].norm._snapshot, contracts.require_sha256, contracts.load_record_bytes,
        contracts.seal_record, native._relational_source_syntax, native._string, native._lean_list, native._need,
        owners[0].validate_reviewed_norm_graph_v3, owners[1].assess_reviewed_norm_admission_v3)
    if definition_application_profile is not None:
        from ..syntax_core import algebra, ast
        functions += (_reviewed_definition_application_copy,
            _reviewed_definition_application_at, _reviewed_definition_application_role_map,
            _reviewed_definition_application_nodes, _reviewed_definition_application_mixed_source,
            _reviewed_definition_application_expand, _reviewed_definition_application_expression,
            _reviewed_definition_application_rows,
            _reviewed_definition_application_prepare_rows, _reviewed_definition_application_lean_helpers,
            _reviewed_definition_application_proof, _reviewed_definition_application_abi_example,
            _reviewed_definition_application_lean,
            algebra.free_variables, algebra.substitute, algebra.LogicExpressionAlgebra.substitute,
            ast.TypedExpression.from_dict, ast.TypedExpression.to_dict, ast.LogicNode.from_dict,
            ast.LogicNode.to_dict, native._mixed_source_witness,
            contracts.require_text, contracts.require_int)
    return tuple((function, getattr(function, "__code__", None)) for function in functions)


def _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs, *,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, offered=None,
        instance_identity_profile=None, definition_application_profile=None,
        physical_request_raw=None, expected_physical_request_sha256=None, physical_bridge_version=1):
    import inspect
    if type(physical_bridge_version) is not int or physical_bridge_version not in (1, 2):
        _fail("explicit supported physical bridge version required")
    if physical_bridge_version == 2 and physical_request_raw is None:
        _fail("physical bridge V2 requires its original request")
    _reviewed_definition_realization_policy(**({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}), **_reviewed_definition_application_kwargs(definition_application_profile))
    for value, label in ((expected_preservation_sha256, "expected_preservation_sha256"),
            (expected_graph_sha256, "expected_graph_sha256"), (expected_admission_sha256, "expected_admission_sha256")):
        contracts.require_sha256(value, label)
    if reviewed_preservation_corpus_sha256(preservation) != expected_preservation_sha256:
        _fail("independent complete original V3 preservation pin differs")
    owners = _reviewed_mixed_preservation_owners()
    norm = owners[1].norm
    physical_owner = None
    physical_callback = None
    physical_owner_pin = None
    if physical_request_raw is not None:
        from . import legal_release_coordinator_v1 as physical_owner
        if type(physical_request_raw) is not bytes:
            _fail("original immutable physical request bytes required")
        contracts.require_sha256(expected_physical_request_sha256, "physical request SHA256")
        if _sha(physical_request_raw) != expected_physical_request_sha256:
            _fail("original physical request differs from independent pin")
        if physical_bridge_version == 2:
            _reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile)
            physical_validator_name = "validate_reviewed_physical_realization_context_v2"
            physical_shared_names = ("_reviewed_physical_realization_policy_v2",
                "prepare_reviewed_physical_definition_realization_corpus_v2",
                "validate_reviewed_physical_definition_realization_corpus_v2",
                "_reviewed_joint_physical_profiles_v2")
        else:
            if instance_identity_profile is not None or definition_application_profile is not None:
                _fail("physical realization selected profiles require a separately closed bridge")
            physical_validator_name = "validate_reviewed_physical_realization_context_v1"
            physical_shared_names = ("_reviewed_physical_realization_policy",
                "prepare_reviewed_physical_definition_realization_corpus_v1",
                "validate_reviewed_physical_definition_realization_corpus_v1")
        globals()[physical_shared_names[0]]()
        def physical_callbacks():
            return (getattr(physical_owner, physical_validator_name),
                *(globals()[name] for name in physical_shared_names), contracts.load_json_bytes)
        physical_callback = physical_owner._release_callback_states_v3(physical_callbacks())
        physical_owner_pin = _sha(Path(physical_owner.__file__).read_bytes())
    elif expected_physical_request_sha256 is not None:
        _fail("physical context cannot be supplied without its original request")


    def original_inputs():
        original = {"preservation": _reviewed_preservation_offered(preservation), "graph": graph, "admission": admission,
            "args": list(args), "kwargs": kwargs, "expected_preservation_sha256": expected_preservation_sha256,
            "expected_graph_sha256": expected_graph_sha256, "expected_admission_sha256": expected_admission_sha256,
            "toolchain": toolchain}
        if instance_identity_profile is not None:
            original["instance_identity_profile"] = instance_identity_profile
        if definition_application_profile is not None:
            original["definition_application_profile"] = definition_application_profile
        if physical_owner is not None:
            original.update(physical_request_raw=physical_request_raw,
                expected_physical_request_sha256=expected_physical_request_sha256)
            if physical_bridge_version == 2:
                original["physical_bridge_version"] = 2
        return original
    detached, commitment = norm._snapshot(original_inputs())
    upstream = ReviewedPreservationCorpusPreparation(detached["preservation"]["manifest_json"],
        tuple(tuple(pair) for pair in detached["preservation"]["files"]))
    pins, callbacks = (_reviewed_definition_application_pins(owners, definition_application_profile),
        _reviewed_definition_realization_callbacks(owners, **_reviewed_definition_application_kwargs(definition_application_profile)))
    offered_commitment = None if offered is None else norm._snapshot(_reviewed_preservation_offered(offered))[1]
    authority, false_flags = dict(owners[2].AUTHORITY), dict(owners[2].FALSE_FLAGS)
    if not authority or not false_flags or any(value is not False for value in [*authority.values(), *false_flags.values()]):
        _fail("realization preparation cannot confer authority")

    def fence():
        if physical_owner is not None:
            globals()[physical_shared_names[0]]()
            physical_owner._release_callback_fence_v3(physical_callbacks(), physical_callback)
            if physical_bridge_version == 2:
                _reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile)
            if _sha(Path(physical_owner.__file__).read_bytes()) != physical_owner_pin:
                _fail("physical realization evidence owner changed during operation")
        if (norm._snapshot(original_inputs())[1] != commitment or norm._snapshot(detached)[1] != commitment
                or _reviewed_definition_application_pins(owners, definition_application_profile) != pins
                or _reviewed_definition_realization_callbacks(owners, **_reviewed_definition_application_kwargs(definition_application_profile)) != callbacks
                or owners[2].AUTHORITY != authority or owners[2].FALSE_FLAGS != false_flags
                or (offered is not None and norm._snapshot(_reviewed_preservation_offered(offered))[1] != offered_commitment)):
            _fail("realization inputs, callbacks, policy, preparation or producer changed during operation")
        _reviewed_definition_realization_policy(**({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}), **_reviewed_definition_application_kwargs(definition_application_profile))
    fence()
    physical_context = None
    if physical_owner is not None:
        physical_context = getattr(physical_owner, physical_validator_name)(
            physical_request_raw, expected_request_sha256=expected_physical_request_sha256)
        fence()
        opening_context_raw = canonical_dag_json_bytes(physical_context)
        physical_context = contracts.load_json_bytes(opening_context_raw,
            expected_sha256=_sha(opening_context_raw))
        if canonical_dag_json_bytes(physical_context) != opening_context_raw:
            _fail("physical realization context snapshot changed")
        fence()
        for field, expected in (("admission_sha256", expected_admission_sha256),
                ("graph_sha256", expected_graph_sha256), ("preservation_sha256", expected_preservation_sha256),
                ("declaration_sha256", detached["admission"]["declaration_sha256"])):
            if physical_context[field] != expected:
                _fail("physical request belongs to another complete realization component: " + field)
        if physical_bridge_version == 2:
            if (physical_context.get("instance_identity_profile") != instance_identity_profile
                    or physical_context.get("definition_application_profile") != definition_application_profile):
                _fail("physical context belongs to another selected realization profile")
        declaration = detached["kwargs"]["preparation_inputs"]["declaration"]
        if (physical_context["cross_references"] != declaration["cross_references"]
                or physical_context["ordered_unit_ids"] != [unit["unit_id"] for unit in declaration["units"]]):
            _fail("physical request source units or reviewed dependencies differ")
        fence()
    validate_reviewed_norm_preservation_corpus_v3(upstream, detached["graph"], detached["admission"],
        *detached["args"], expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **detached["kwargs"],
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}))
    fence()
    signature = inspect.signature(owners[1].assess_reviewed_norm_admission_v3)
    bound = signature.bind(*detached["args"], **detached["kwargs"])
    if set(bound.arguments) != set(signature.parameters):
        _fail("complete original V3 replay inputs required for realization")
    result = _reviewed_definition_realization_project(upstream, detached["graph"], detached["admission"],
        bound.arguments, owners, pins, commitment, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain,
        **({"physical_context": physical_context, "physical_context_owner_sha256": physical_owner_pin,
            "physical_bridge_version": physical_bridge_version} if physical_context is not None else {}),
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}),
        **_reviewed_definition_application_kwargs(definition_application_profile))
    result_envelope = _reviewed_preservation_offered(result)
    # Detach all buffers before another callback can retain or change the
    # serializer's temporary containers. Strings and these tuple pairs are
    # private immutable values; no later callback receives them.
    frozen_manifest_json = result_envelope["manifest_json"]
    frozen_files = tuple(tuple(pair) for pair in result_envelope["files"])
    result_envelope = {"manifest_json": frozen_manifest_json,
        "files": [list(pair) for pair in frozen_files]}
    result_commitment = reviewed_preservation_corpus_sha256(result)
    fence()
    if offered is not None and result != offered:
        _fail("realization differs from complete current source and preservation regeneration")
    if (reviewed_preservation_corpus_sha256(result) != result_commitment
            or _reviewed_preservation_offered(result) != result_envelope):
        _fail("actual realization result changed during final checks")
    fence()
    if _reviewed_preservation_offered(result) != result_envelope:
        _fail("actual realization result changed at final callback boundary")
    # Construct the detached return value before the LAST input/producer fence.
    # There is no result-visible serialization or callback after that fence.
    closed_result = ReviewedPreservationCorpusPreparation(frozen_manifest_json, frozen_files)
    if physical_owner is not None:
        closed_context = getattr(physical_owner, physical_validator_name)(
            physical_request_raw, expected_request_sha256=expected_physical_request_sha256)
        if canonical_dag_json_bytes(closed_context) != opening_context_raw:
            _fail("complete physical evidence generation changed during realization")
    fence()
    return closed_result


def prepare_reviewed_definition_realization_corpus_v1(preservation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Prepare source-bound constructed and explicitly selected conditional obligations."""
    return _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain,
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}),
        **_reviewed_definition_application_kwargs(definition_application_profile))


def validate_reviewed_definition_realization_corpus_v1(preparation, preservation, graph, admission, *args,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Regenerate all obligations and exact unchanged V3 sources under live replay."""
    _reviewed_definition_realization_profile(instance_identity_profile, **_reviewed_definition_application_kwargs(definition_application_profile))
    contracts.require_sha256(expected_realization_sha256, "expected_realization_sha256")
    if reviewed_preservation_corpus_sha256(preparation) != expected_realization_sha256:
        _fail("independent complete realization preparation pin differs")
    return _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain,
        **({"instance_identity_profile": instance_identity_profile} if instance_identity_profile is not None else {}),
        **_reviewed_definition_application_kwargs(definition_application_profile), offered=preparation)


__all__ += ["REVIEWED_DEFINITION_REALIZATION_SCHEMA", "REVIEWED_DEFINITION_REALIZATION_PROFILE",
    "REVIEWED_DEFINITION_REALIZATION_ROOT", "prepare_reviewed_definition_realization_corpus_v1",
    "validate_reviewed_definition_realization_corpus_v1"]


def _reviewed_definition_application_kwargs(definition_application_profile):
    """An explicit theorem domain; retained objects cannot select it."""
    if definition_application_profile is None:
        return {}
    if (type(definition_application_profile) is not str
            or definition_application_profile != "whole-norm-definition-expansion/v1"):
        _fail("explicit whole-norm-definition-expansion/v1 profile required")
    return {"definition_application_profile": definition_application_profile}


def _reviewed_definition_application_copy(value):
    import json
    return json.loads(canonical_dag_json_bytes(value))


def _reviewed_definition_application_at(expression, path):
    if type(path) is not str or re.fullmatch(r"/root(?:/arguments/[01])*", path) is None:
        _fail("exact nonmodal original definition application path required")
    selected = expression
    for token in path.split("/")[1:]:
        selected = selected[int(token)] if type(selected) is list else selected[token]
    return selected


def _reviewed_definition_application_role_map(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        _fail("bounded complete definition application role table required")
    result = {}
    for row in rows:
        if (type(row) is not dict or set(row) != {"symbol", "roles"}
                or type(row["symbol"]) is not str or row["symbol"] in result
                or type(row["roles"]) is not list or not 1 <= len(row["roles"]) <= 8
                or any(type(label) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", label) is None
                       for label in row["roles"])
                or len(set(row["roles"])) != len(row["roles"])):
            _fail("exact distinct ordered definition application roles required")
        result[row["symbol"]] = row["roles"]
    return result


def _reviewed_definition_application_nodes(root, path="/root"):
    """Bounded original/derived node inventory, including opaque extension IDs."""
    result, identifiers, binders = [], set(), set()
    def visit(node, at, depth):
        if depth > 64 or len(result) >= 4096 or type(node) is not dict:
            _fail("complete definition expansion exceeds original node/depth bounds")
        identity = node.get("node_id")
        if type(identity) is not str or not identity or identity in identifiers:
            _fail("distinct complete definition expansion node identities required")
        identifiers.add(identity); result.append((at, node))
        kind, arguments, bound = node.get("kind"), node.get("arguments"), node.get("binders")
        arities = {"variable": 0, "not": 1, "and": 2, "or": 2, "implies": 2,
            "iff": 2, "forall": 1, "exists": 1, "equality": 2, "extension": 0}
        if (type(arguments) is not list or type(bound) is not list
                or (kind == "predicate" and not 1 <= len(arguments) <= 8)
                or (kind != "predicate" and (kind not in arities or len(arguments) != arities[kind]))
                or (kind not in ("forall", "exists") and bound)):
            _fail("exact complete supported expansion constructor arity required")
        if kind in ("forall", "exists"):
            if len(node.get("binders", ())) != 1:
                _fail("single original definition application binder required")
            name = node["binders"][0]["name"]
            if name in binders:
                _fail("globally unique original norm binders required for definition expansion")
            binders.add(name)
        for ordinal, child in enumerate(node.get("arguments", ())):
            visit(child, at + "/arguments/" + str(ordinal), depth + 1)
        if node.get("kind") == "extension":
            extension = node["extension"]
            identity = extension["node_id"]
            if identity in identifiers:
                _fail("distinct opaque extension identity required")
            identifiers.add(identity)
            for ordinal, child in enumerate(extension["children"]):
                visit(child, at + "/extension/children/" + str(ordinal), depth + 1)
    visit(root, path, 0)
    return result, identifiers, binders


def _reviewed_definition_application_mixed_source(expression, roles, native):
    """Render the exact root using a canonical, used-declaration-only view.

    The existing renderer deliberately rejects unused declarations. Expansion
    removes H while the retained full signature/role union must keep H. Only
    this ephemeral rendering view drops unused declarations, receives a fresh
    valid content digest, and contributes the returned root source string.
    Its signature, role, identity and digest outputs are never substituted for
    the full canonical expanded expression or its retained union role table.
    """
    from ..syntax_core.ast import TypedExpression
    used = {node["symbol"] for _, node in _reviewed_definition_application_nodes(expression["root"])[0]
            if node["kind"] == "predicate"}
    view = _reviewed_definition_application_copy(expression)
    view["signature"]["symbols"] = [row for row in view["signature"]["symbols"] if row["name"] in used]
    view.pop("content_digest", None)
    view = TypedExpression.from_dict(view).to_dict()
    return native._mixed_source_witness(view, [row for row in roles if row["symbol"] in used])["source"]


def _reviewed_definition_application_expand(original, original_roles, definition, definition_roles,
        selection, unit, definition_unit):
    from ..syntax_core import algebra, ast
    from . import legal_native_ast_preservation as native
    parameter = selection["definition_binder"]
    root = definition["root"]
    if (root["kind"] != "forall" or root["binders"] != [parameter] or len(root["arguments"]) != 1
            or root["arguments"][0]["kind"] != "iff" or len(root["arguments"][0]["arguments"]) != 2):
        _fail("exact original universal source definition required for expansion")
    head, body = root["arguments"][0]["arguments"]
    if (body != selection["body_typed_node"] or algebra.free_variables(ast.LogicNode.from_dict(body))
            != frozenset({parameter["name"]})):
        _fail("complete original unary definition body and sole free parameter required")
    source_roles = _reviewed_definition_application_role_map(definition_roles)
    old_roles = _reviewed_definition_application_role_map(original_roles)
    if (native._relational_source_syntax(body, source_roles) != selection["body_role_ast"]
            or native._relational_source_syntax(head, source_roles) != selection["head_role_ast"]):
        _fail("definition application body roles differ from original source witness")
    _, old_ids, binder_names = _reviewed_definition_application_nodes(original["root"])
    old_ids |= _reviewed_definition_application_nodes(definition["root"])[1]
    body_nodes = _reviewed_definition_application_nodes(body, selection["body_typed_path"])[0]
    if any(node["kind"] not in ("predicate", "not", "and", "or") for _, node in body_nodes
           if node["kind"] != "variable"):
        _fail("nonrecursive binder-free Boolean source body required for expansion")
    used_body = {node["symbol"] for _, node in body_nodes if node["kind"] == "predicate"}
    declarations = {row["name"]: row for row in original["signature"]["symbols"]}
    if (set(old_roles) != set(declarations)
            or source_roles.get(selection["head_symbol"]) != selection["head_roles"]
            or old_roles.get(selection["head_symbol"]) != selection["head_roles"]):
        _fail("complete original declaration/role binding required")
    signature = _reviewed_definition_application_copy(original["signature"])
    expanded_roles = _reviewed_definition_application_copy(original_roles)
    for declared in definition["signature"]["symbols"]:
        name = declared["name"]
        if name not in used_body:
            continue
        if (name == selection["head_symbol"] or len(declared["domain"]) != 1
                or declared["domain"][0].get("name") != "Object" or declared["range"].get("name") != "Bool"
                or len(source_roles.get(name, ())) != 1 or name in binder_names):
            _fail("capture-free unary Object body declaration required; sort/binder collision refused")
        if name in declarations:
            if declarations[name] != declared or old_roles[name] != source_roles[name]:
                _fail("definition body sort, arity or ordered role collision refused")
        else:
            signature["symbols"].append(_reviewed_definition_application_copy(declared))
            expanded_roles.append({"symbol": name, "roles": list(source_roles[name])})
    if len(signature["symbols"]) > 64:
        _fail("complete expanded signature exceeds original declaration bound")
    if signature != original["signature"]:
        signature["signature_id"] = "definition-expansion-signature:" + _sha(canonical_dag_json_bytes(signature))
    expanded = _reviewed_definition_application_copy(original)
    expanded["signature"] = signature
    selected = [row for row in selection["occurrences"] if row["unit_id"] == unit["unit_id"]]
    records = []
    for occurrence in selected:
        path = occurrence["typed_path"]
        old = _reviewed_definition_application_at(original, path)
        if old != occurrence["typed_node"] or old["arguments"] != [occurrence["argument"]]:
            _fail("exact original selected head subtree required before replacement")
        replacement = algebra.substitute(ast.LogicNode.from_dict(body), parameter["name"],
            ast.LogicNode.from_dict(occurrence["argument"])).to_dict()
        ids = []
        def identify(node, source_node, source_path, target_path):
            identity = "definition-expansion:" + _sha(canonical_dag_json_bytes({
                "definition_unit_id": definition_unit["unit_id"],
                "definition_ir_sha256": definition_unit["complete_ir_sha256"],
                "unit_id": unit["unit_id"], "source_occurrence_cid": unit["source_occurrence_cid"],
                "source_typed_path": source_path, "expanded_typed_path": target_path}))
            if identity in old_ids:
                _fail("new definition expansion identity collides with an original node")
            node["node_id"] = identity
            ids.append({"source_typed_path": source_path, "expanded_typed_path": target_path, "node_id": identity})
            if node["kind"] != source_node["kind"] or len(node["arguments"]) != len(source_node["arguments"]):
                _fail("capture-safe body substitution changed the source constructor population")
            for ordinal, (child, source_child) in enumerate(zip(node["arguments"], source_node["arguments"], strict=True)):
                identify(child, source_child, source_path + "/arguments/" + str(ordinal),
                    target_path + "/arguments/" + str(ordinal))
        identify(replacement, body, selection["body_typed_path"], path)
        tokens = path.split("/")
        parent = expanded
        for token in tokens[1:-1]:
            parent = parent[int(token)] if type(parent) is list else parent[token]
        if type(parent) is list:
            parent[int(tokens[-1])] = replacement
        else:
            parent[tokens[-1]] = replacement
        records.append({"target_typed_path": path, "definition_body_typed_path": selection["body_typed_path"],
            "definition_body_typed_sha256": selection["body_typed_sha256"],
            "source_parameter": parameter, "target_argument": occurrence["argument"], "inserted_node_ids": ids})
    expanded.pop("content_digest", None)
    expanded = ast.TypedExpression.from_dict(expanded).to_dict()
    _reviewed_definition_application_nodes(expanded["root"])
    if unit["relational_profile"] == "authored-many-sorted-relational-deontic/v1":
        _reviewed_definition_application_mixed_source(expanded, expanded_roles, native)
    else:
        native._relational_source_syntax(expanded["root"], _reviewed_definition_application_role_map(expanded_roles))
    return expanded, expanded_roles, records


def _reviewed_definition_application_expression(row, name):
    """Decode a lossless AST transport without changing record or AST bounds.

    Encoded expressions do not borrow enclosing manifest nesting depth. The
    local JSON depth guard accounts for the existing 64 AST levels plus their
    argument arrays and fixed typed-expression/signature wrappers. The original
    25,000 ordinary JSON node/1MiB byte bounds and independent AST/render bounds
    still apply; decoded values never replace the retained canonical text.
    """
    import json
    from ..syntax_core.ast import TypedExpression
    if (type(row) is not dict or name not in ("definition", "original", "expanded")
            or row.get("typed_expression_transport") != "canonical-dag-json-text/v1"):
        _fail("explicit canonical-dag-json-text/v1 typed expression transport required")
    text = row.get(name + "_typed_expression")
    if type(text) is not str:
        _fail("lossless canonical typed expression text required")
    try:
        raw = text.encode("utf-8")
        if not raw or len(raw) > contracts.MAX_RECORD_BYTES:
            _fail("typed expression transport exceeds existing record byte bound")
        maximum_depth = 2 * 64 + 16
        depth, quoted, escaped = 0, False, False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                if depth > maximum_depth:
                    _fail("typed expression encoded JSON exceeds bounded AST wrapper depth")
            elif character in "]}":
                depth -= 1
                if depth < 0:
                    _fail("malformed typed expression encoded JSON nesting")
        if quoted or depth:
            _fail("malformed typed expression encoded JSON nesting")
        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    _fail("duplicate typed expression JSON key")
                value[key] = item
            return value
        def constant(value):
            _fail("nonfinite typed expression JSON constant refused")
        expression = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        pending, remaining = [(expression, 0)], contracts.MAX_JSON_NODES
        while pending:
            value, level = pending.pop()
            remaining -= 1
            if remaining < 0 or level > maximum_depth:
                _fail("typed expression transport exceeds existing JSON node or AST wrapper depth bound")
            if type(value) is dict:
                for key in value:
                    contracts.require_text(key, "typed expression JSON key", max_bytes=4096)
                pending.extend((item, level + 1) for item in value.values())
            elif type(value) is list:
                pending.extend((item, level + 1) for item in value)
            elif type(value) is str:
                contracts.require_text(value, "typed expression JSON string", allow_empty=True,
                    max_bytes=contracts.MAX_RECORD_BYTES)
            elif type(value) is int:
                contracts.require_int(value, "typed expression JSON integer",
                    minimum=-contracts.MAX_INTEGER, maximum=contracts.MAX_INTEGER)
        if type(expression) is not dict or type(expression.get("root")) is not dict:
            _fail("complete typed expression object/root required")
        _reviewed_definition_application_nodes(expression["root"])
        if (canonical_dag_json_bytes(expression) != raw
                or _sha(raw) != row.get(name + "_typed_expression_sha256")
                or TypedExpression.from_dict(expression).to_dict() != expression):
            _fail("canonical typed expression transport, SHA or exact AST roundtrip differs")
        return expression
    except (TypeError, ValueError, KeyError, UnicodeError, RecursionError, OverflowError) as error:
        _fail("invalid bounded canonical typed expression transport: " + type(error).__name__)


def _reviewed_definition_application_rows(rows, selection, units, *, definition_application_profile):
    """Shared current-source shape/derivation checker reused by Native/cache owners."""
    _reviewed_definition_application_kwargs(definition_application_profile)
    if definition_application_profile is None:
        _fail("explicit definition application rows require the selected profile")
    definitions = [unit for unit in units if unit["kind"] == "definition"]
    norms = [unit for unit in units if unit["kind"] == "norm"]
    if (len(definitions) != 1 or type(rows) is not list
            or any(type(row) is not dict for row in rows)
            or [row.get("unit_id") for row in rows] != [unit["unit_id"] for unit in norms]):
        _fail("one exact ordered whole-norm application row per original norm required")
    definition_unit = definitions[0]
    keys = {"unit_id", "definition_unit_id", "definition_use_record_cid", "scope_record_cid",
        "interpretation_record_cid", "definition_typed_expression", "definition_typed_expression_sha256",
        "original_typed_expression", "original_typed_expression_sha256", "expanded_typed_expression",
        "expanded_typed_expression_sha256", "original_argument_roles", "expanded_argument_roles",
        "target_typed_paths", "replacement_records", "typed_expression_transport"}
    donor = None
    for row, unit in zip(rows, norms, strict=True):
        if type(row) is not dict or set(row) != keys:
            _fail("closed complete whole-norm application record required")
        expressions = {name: _reviewed_definition_application_expression(row, name)
            for name in ("definition", "original", "expanded")}
        definition = expressions["definition"]
        if donor is not None and donor != definition:
            _fail("all norms require the same exact original source definition")
        donor = definition
        uses = [use for use in selection["definition_use_records"]
                if use["definition_unit_id"] == definition_unit["unit_id"] and use["use_unit_id"] == unit["unit_id"]]
        if (len(uses) != 1 or row["definition_unit_id"] != definition_unit["unit_id"]
                or row["definition_use_record_cid"] != uses[0]["record_cid"]
                or row["scope_record_cid"] != unit["scope_record_cid"]
                or row["scope_record_cid"] != definition_unit["scope_record_cid"]
                or row["interpretation_record_cid"] != unit["interpretation_record_cid"]
                or row["interpretation_record_cid"] != definition_unit["interpretation_record_cid"]):
            _fail("exact original governing use, scope and interpretation required")
        original = expressions["original"]
        if ({k: v for k, v in original["signature"].items() if k != "symbols"} != unit["signature_header"]
                or {k: v for k, v in definition["signature"].items() if k != "symbols"} != definition_unit["signature_header"]):
            _fail("whole-norm original typed signature differs from preserved unit")
        paths = [value["typed_path"] for value in selection["occurrences"] if value["unit_id"] == unit["unit_id"]]
        if row["target_typed_paths"] != paths:
            _fail("complete original selected occurrence paths required for every norm")
        # The recorded expanded roles recover body labels, independently tied
        # to the retained source-role witness by _expand. The exact current
        # declaration/IR binding is supplied by full original Shared replay.
        recovered = _reviewed_definition_application_role_map(row["expanded_argument_roles"])
        recovered[selection["head_symbol"]] = selection["head_roles"]
        definition_roles = [{"symbol": name, "roles": labels} for name, labels in recovered.items()]
        expected, expected_roles, records = _reviewed_definition_application_expand(original,
            row["original_argument_roles"], definition, definition_roles, selection, unit, definition_unit)
        if (expected != expressions["expanded"] or expected_roles != row["expanded_argument_roles"]
                or records != row["replacement_records"]):
            _fail("whole-norm expansion differs from exact original source-body derivation")
    return rows


def _reviewed_definition_application_prepare_rows(selection, units, admission, definition_application_profile):
    _reviewed_definition_application_kwargs(definition_application_profile)
    admitted = {unit["unit_id"]: unit["canonical_ir"] for unit in admission["units"]}
    definition_unit = next(unit for unit in units if unit["kind"] == "definition")
    definition = admitted[definition_unit["unit_id"]]
    rows = []
    for unit in units:
        if unit["kind"] != "norm":
            continue
        original = admitted[unit["unit_id"]]
        expanded, roles, records = _reviewed_definition_application_expand(original["typed_expression"],
            original["argument_roles"], definition["typed_expression"], definition["argument_roles"],
            selection, unit, definition_unit)
        use = next(value for value in selection["definition_use_records"] if value["use_unit_id"] == unit["unit_id"])
        row = {"unit_id": unit["unit_id"], "definition_unit_id": definition_unit["unit_id"],
            "definition_use_record_cid": use["record_cid"], "scope_record_cid": unit["scope_record_cid"],
            "interpretation_record_cid": unit["interpretation_record_cid"],
            "definition_typed_expression": definition["typed_expression"],
            "original_typed_expression": original["typed_expression"], "expanded_typed_expression": expanded,
            "original_argument_roles": original["argument_roles"], "expanded_argument_roles": roles,
            "target_typed_paths": [value["target_typed_path"] for value in records], "replacement_records": records}
        row["typed_expression_transport"] = "canonical-dag-json-text/v1"
        for name in ("definition", "original", "expanded"):
            raw = canonical_dag_json_bytes(row[name + "_typed_expression"])
            row[name + "_typed_expression"] = raw.decode("utf-8")
            row[name + "_typed_expression_sha256"] = _sha(raw)
        rows.append(row)
    return _reviewed_definition_application_rows(rows, selection, units,
        definition_application_profile=definition_application_profile)


def _reviewed_definition_application_lean_helpers(include_mixed):
    """Independent finite AST transforms; no denotation/Iff is an input."""
    text = r'''
set_option backward.match.sparseCases false in
def sourceObjectDefinitionBody (parameter head role : String) :
    LegalRelationalAstPreservation.RoleFormula → Option LegalRelationalAstPreservation.RoleFormula
  | .universal binder (.equivalence (.predicate name roles variables) body) =>
      if binder == parameter && name == head && roles == [role] && variables == [parameter]
        then some body else none
  | _ => none

set_option backward.match.sparseCases false in
def instantiateObjectDefinitionBody (parameter argumentName : String) :
    LegalRelationalAstPreservation.RoleFormula → Option LegalRelationalAstPreservation.RoleFormula
  | .predicate name roles variables =>
      if variables == [parameter] then some (.predicate name roles [argumentName]) else none
  | .negation body => do
      let changed ← instantiateObjectDefinitionBody parameter argumentName body
      pure (.negation changed)
  | .conjunction left right => do
      let l ← instantiateObjectDefinitionBody parameter argumentName left
      let r ← instantiateObjectDefinitionBody parameter argumentName right
      pure (.conjunction l r)
  | .disjunction left right => do
      let l ← instantiateObjectDefinitionBody parameter argumentName left
      let r ← instantiateObjectDefinitionBody parameter argumentName right
      pure (.disjunction l r)
  | _ => none

set_option backward.match.sparseCases false in
def objectDefinitionExpansionAt (head role argumentName : String)
    (replacement : LegalRelationalAstPreservation.RoleFormula) :
    List Nat → LegalRelationalAstPreservation.RoleFormula → Option LegalRelationalAstPreservation.RoleFormula
  | [], .predicate name roles variables =>
      if name == head && roles == [role] && variables == [argumentName] then some replacement else none
  | 0 :: path, .negation body => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path body
      pure (.negation changed)
  | 0 :: path, .conjunction left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path left
      pure (.conjunction changed right)
  | 1 :: path, .conjunction left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path right
      pure (.conjunction left changed)
  | 0 :: path, .disjunction left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path left
      pure (.disjunction changed right)
  | 1 :: path, .disjunction left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path right
      pure (.disjunction left changed)
  | 0 :: path, .implication left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path left
      pure (.implication changed right)
  | 1 :: path, .implication left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path right
      pure (.implication left changed)
  | 0 :: path, .equivalence left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path left
      pure (.equivalence changed right)
  | 1 :: path, .equivalence left right => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path right
      pure (.equivalence left changed)
  | 0 :: path, .universal name body => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path body
      pure (.universal name changed)
  | 0 :: path, .existential name body => do
      let changed ← objectDefinitionExpansionAt head role argumentName replacement path body
      pure (.existential name changed)
  | _, _ => none

set_option backward.match.sparseCases false in
def applyObjectDefinitionExpansions (source definition : LegalRelationalAstPreservation.RoleFormula)
    (parameter head role : String) (targets : List (List Nat × String)) :
    Option LegalRelationalAstPreservation.RoleFormula := do
  let body ← sourceObjectDefinitionBody parameter head role definition
  targets.foldl (fun current target => do
    let original ← current
    let replacement ← instantiateObjectDefinitionBody parameter target.2 body
    objectDefinitionExpansionAt head role target.2 replacement target.1 original) (some source)
'''
    if not include_mixed:
        return text
    return text + r'''
set_option backward.match.sparseCases false in
def restrictObjectAtoms {Object EventFrame TimeFrame : Type}
    (atoms : String → List (String × LegalMixedRelationalAstPreservation.MixedEntity Object EventFrame TimeFrame) → Nat → Prop)
    (name : String) (values : List (String × Object)) (t : Nat) : Prop :=
  atoms name (values.map fun pair => (pair.1, Sum.inr (Sum.inl pair.2))) t

set_option backward.match.sparseCases false in
def instantiateMixedDefinitionBody (parameter argumentName : String) :
    LegalRelationalAstPreservation.RoleFormula → List String →
    Option (LegalMixedRelationalAstPreservation.MixedFormula × List String)
  | .predicate name _ variables, nodeId :: variableId :: rest =>
      if variables == [parameter] then
        some (.predicate nodeId name [⟨variableId, argumentName, .object⟩], rest) else none
  | .negation body, nodeId :: rest => do
      let changed ← instantiateMixedDefinitionBody parameter argumentName body rest
      pure (.negation nodeId changed.1, changed.2)
  | .conjunction left right, nodeId :: rest => do
      let l ← instantiateMixedDefinitionBody parameter argumentName left rest
      let r ← instantiateMixedDefinitionBody parameter argumentName right l.2
      pure (.conjunction nodeId l.1 r.1, r.2)
  | .disjunction left right, nodeId :: rest => do
      let l ← instantiateMixedDefinitionBody parameter argumentName left rest
      let r ← instantiateMixedDefinitionBody parameter argumentName right l.2
      pure (.disjunction nodeId l.1 r.1, r.2)
  | _, _ => none

set_option backward.match.sparseCases false in
def mixedDefinitionExpansionAt (head argumentName : String)
    (replacement : LegalMixedRelationalAstPreservation.MixedFormula) :
    List Nat → LegalMixedRelationalAstPreservation.MixedFormula → Option LegalMixedRelationalAstPreservation.MixedFormula
  | [], .predicate _ name [⟨_, argument, .object⟩] =>
      if name == head && argument == argumentName then some replacement else none
  | 0 :: path, .negation identity body => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path body
      pure (.negation identity changed)
  | 0 :: path, .conjunction identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path left
      pure (.conjunction identity changed right)
  | 1 :: path, .conjunction identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path right
      pure (.conjunction identity left changed)
  | 0 :: path, .disjunction identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path left
      pure (.disjunction identity changed right)
  | 1 :: path, .disjunction identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path right
      pure (.disjunction identity left changed)
  | 0 :: path, .implication identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path left
      pure (.implication identity changed right)
  | 1 :: path, .implication identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path right
      pure (.implication identity left changed)
  | 0 :: path, .equivalence identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path left
      pure (.equivalence identity changed right)
  | 1 :: path, .equivalence identity left right => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path right
      pure (.equivalence identity left changed)
  | 0 :: path, .universal identity name sort body => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path body
      pure (.universal identity name sort changed)
  | 0 :: path, .existential identity name sort body => do
      let changed ← mixedDefinitionExpansionAt head argumentName replacement path body
      pure (.existential identity name sort changed)
  | _, _ => none

set_option backward.match.sparseCases false in
def applyMixedDefinitionExpansions (source : LegalMixedRelationalAstPreservation.MixedFormula)
    (definition : LegalRelationalAstPreservation.RoleFormula) (parameter head role : String)
    (targets : List (List Nat × (String × List String))) : Option LegalMixedRelationalAstPreservation.MixedFormula := do
  let body ← sourceObjectDefinitionBody parameter head role definition
  targets.foldl (fun current target => do
    let original ← current
    let replacement ← instantiateMixedDefinitionBody parameter target.2.1 body target.2.2
    if replacement.2.isEmpty then
      mixedDefinitionExpansionAt head target.2.1 replacement.1 target.1 original else none) (some source)
'''


def _reviewed_definition_application_proof(original, expanded, paths):
    """Constructive congruence over the original logical context only.

    A head leaf uses the exact independently denoted source definition.
    Unchanged subtrees (especially opaque modal payloads) use Iff.rfl; no
    proposition rewriting, extensionality, desired-Iff input or modal law.
    """
    selected = set(paths)
    counter = 0
    def visit(before, after, path, environment):
        nonlocal counter
        if path in selected:
            variable = before["arguments"][0]["symbol"]
            if variable not in environment:
                _fail("whole-norm head has no exact original bound Object valuation")
            return "(hSourceDefinition " + environment[variable] + ")"
        if before == after:
            return "Iff.rfl"
        kind = before["kind"]
        if kind != after["kind"] or before["binders"] != after["binders"] or before["node_id"] != after["node_id"]:
            _fail("whole-norm expansion changed its original logical context")
        if kind in ("forall", "exists"):
            variable = "bound" + str(counter); counter += 1
            child = visit(before["arguments"][0], after["arguments"][0], path + "/arguments/0",
                {**environment, before["binders"][0]["name"]: variable})
            if kind == "forall":
                return "(Iff.intro (fun h " + variable + " => (" + child + ").mp (h " + variable + ")) (fun h " + variable + " => (" + child + ").mpr (h " + variable + ")))"
            return "(Iff.intro (fun ⟨" + variable + ", h⟩ => ⟨" + variable + ", (" + child + ").mp h⟩) (fun ⟨" + variable + ", h⟩ => ⟨" + variable + ", (" + child + ").mpr h⟩))"
        if kind == "not":
            child = visit(before["arguments"][0], after["arguments"][0], path + "/arguments/0", environment)
            return "(Iff.intro (fun h value => h ((" + child + ").mpr value)) (fun h value => h ((" + child + ").mp value)))"
        if kind not in ("and", "or", "implies", "iff"):
            _fail("only selected heads and original nonmodal logical constructors may change")
        left = visit(before["arguments"][0], after["arguments"][0], path + "/arguments/0", environment)
        right = visit(before["arguments"][1], after["arguments"][1], path + "/arguments/1", environment)
        if kind == "and":
            return "(Iff.intro (fun h => ⟨(" + left + ").mp h.1, (" + right + ").mp h.2⟩) (fun h => ⟨(" + left + ").mpr h.1, (" + right + ").mpr h.2⟩))"
        if kind == "or":
            return "(Iff.intro (fun h => Or.elim h (fun value => Or.inl ((" + left + ").mp value)) (fun value => Or.inr ((" + right + ").mp value))) (fun h => Or.elim h (fun value => Or.inl ((" + left + ").mpr value)) (fun value => Or.inr ((" + right + ").mpr value))))"
        if kind == "implies":
            return "(Iff.intro (fun h value => (" + right + ").mp (h ((" + left + ").mpr value))) (fun h value => (" + right + ").mpr (h ((" + left + ").mp value))))"
        return "(Iff.intro (fun h => Iff.trans (Iff.symm (" + left + ")) (Iff.trans h (" + right + "))) (fun h => Iff.trans (" + left + ") (Iff.trans h (Iff.symm (" + right + ")))))"
    return visit(original, expanded, "/root", {})


def _reviewed_definition_application_abi_example(unit, definition_module):
    """Independently form a typed consumer from original module constants.

    Do not accept the producer's theorem declaration or its premise text as
    input: an extra desired-Iff/constructed-atoms-only ABI must fail Lean.
    """
    obj, mix = "LegalRelationalAstPreservation", "LegalMixedRelationalAstPreservation"
    n, original = str(unit["ordinal"]), unit["instance_module"]
    theorem = "unit_" + n + "_whole_norm_definition_expansion"
    if unit["child_family"] != "tdfol":
        return ("example : ∀ {Object Agent : Type} (base : " + obj + ".Interpretation Object Agent)\n"
            + "    (atoms : String → List (String × Object) → Nat → Prop) (t : Nat),\n"
            + "    " + obj + ".roleDenote base atoms " + definition_module + ".typedSourceAst " + obj + ".emptyEnvironment t →\n"
            + "    (" + obj + ".roleDenote base atoms " + original + ".typedSourceAst " + obj + ".emptyEnvironment t ↔\n"
            + "      " + obj + ".roleDenote base atoms expandedNormAst_" + n + " " + obj + ".emptyEnvironment t) := @" + theorem + "\n")
    entity = mix + ".MixedEntity Object EventFrame TimeFrame"
    return ("example : ∀ {Object Agent EventFrame TimeFrame : Type}\n"
        + "    (objectBase : " + obj + ".Interpretation Object Agent)\n"
        + "    (mixedBase : " + mix + ".Interpretation (" + entity + ") Unit)\n"
        + "    (mixedAtoms : String → List (String × " + entity + ") → Nat → Prop) (t : Nat),\n"
        + "    " + obj + ".roleDenote objectBase (restrictObjectAtoms mixedAtoms) " + definition_module + ".typedSourceAst " + obj + ".emptyEnvironment t →\n"
        + "    (" + mix + ".mixedRoleDenote mixedBase mixedAtoms " + original + ".mixedArgumentRoles " + original + ".typedMixedAst " + mix + ".emptyCountedEnvironment t ↔\n"
        + "      " + mix + ".mixedRoleDenote mixedBase mixedAtoms expandedNormRoles_" + n + " expandedNormAst_" + n + " " + mix + ".emptyCountedEnvironment t) := @" + theorem + "\n")


def _reviewed_definition_application_lean(selection, units, applications, native, module):
    obj, mix = "LegalRelationalAstPreservation", "LegalMixedRelationalAstPreservation"
    norms = [unit for unit in units if unit["kind"] == "norm"]
    text = _reviewed_definition_application_lean_helpers(any(unit["child_family"] == "tdfol" for unit in norms))
    names, bindings = [], []
    definition_module = selection["definition_instance_module"]
    for unit, row in zip(norms, applications, strict=True):
        n, original = str(unit["ordinal"]), unit["instance_module"]
        is_mixed = unit["child_family"] == "tdfol"
        original_expression = _reviewed_definition_application_expression(row, "original")
        expanded = _reviewed_definition_application_expression(row, "expanded")
        roles = _reviewed_definition_application_role_map(row["expanded_argument_roles"])
        if is_mixed:
            ast_source = _reviewed_definition_application_mixed_source(expanded, row["expanded_argument_roles"], native)
            text += "def expandedNormAst_" + n + " : " + mix + ".MixedFormula := " + ast_source + "\n"
            role_source = "[" + ", ".join("⟨" + native._string(value["symbol"]) + ", " + native._lean_list(value["roles"]) + "⟩" for value in row["expanded_argument_roles"]) + "]"
            text += "def expandedNormRoles_" + n + " : List " + mix + ".MixedRoleRow := " + role_source + "\n"
        else:
            text += "def expandedNormAst_" + n + " : " + obj + ".RoleFormula := " + native._relational_source_syntax(expanded["root"], roles) + "\n"
        targets = []
        for replacement in row["replacement_records"]:
            tokens = replacement["target_typed_path"].split("/")
            path = "[" + ", ".join(tokens[index] for index in range(3, len(tokens), 2)) + "]"
            variable = native._string(replacement["target_argument"]["symbol"])
            if is_mixed:
                ids = native._lean_list([value["node_id"] for value in replacement["inserted_node_ids"]])
                targets.append("(" + path + ", (" + variable + ", " + ids + "))")
            else:
                targets.append("(" + path + ", " + variable + ")")
        source = (("applyMixedDefinitionExpansions " + original + ".typedMixedAst " if is_mixed else
            "applyObjectDefinitionExpansions " + original + ".typedSourceAst ")
            + definition_module + ".typedSourceAst " + native._string(selection["definition_binder"]["name"])
            + " " + native._string(selection["head_symbol"]) + " " + native._string(selection["head_roles"][0]))
        exact_name = "unit_" + n + "_expansion_source_exact"
        statement = ": " + source + " [" + ", ".join(targets) + "] = some expandedNormAst_" + n
        text += "theorem " + exact_name + " " + statement + " := by\n  rfl\n#print axioms " + exact_name + "\n"
        names.append(module + "." + exact_name)
        bindings.append({"theorem": names[-1], "binding": {"kind": "whole_norm_expansion_source_exact", "unit_id": unit["unit_id"],
            "original_typed_expression_sha256": row["original_typed_expression_sha256"],
            "expanded_typed_expression_sha256": row["expanded_typed_expression_sha256"],
            "replacement_records": row["replacement_records"], "digest_values_are_not_in_kernel_hash_claims": True},
            "declaration": "theorem " + exact_name + " " + statement})
        if is_mixed:
            entity = mix + ".MixedEntity Object EventFrame TimeFrame"
            parameters = ("{Object Agent EventFrame TimeFrame : Type} (objectBase : " + obj + ".Interpretation Object Agent) "
                + "(mixedBase : " + mix + ".Interpretation (" + entity + ") Unit) "
                + "(mixedAtoms : String → List (String × " + entity + ") → Nat → Prop) (t : Nat) ")
            premise = obj + ".roleDenote objectBase (restrictObjectAtoms mixedAtoms) " + definition_module + ".typedSourceAst " + obj + ".emptyEnvironment t"
            conclusion = (mix + ".mixedRoleDenote mixedBase mixedAtoms " + original + ".mixedArgumentRoles " + original + ".typedMixedAst " + mix + ".emptyCountedEnvironment t ↔\n    "
                + mix + ".mixedRoleDenote mixedBase mixedAtoms expandedNormRoles_" + n + " expandedNormAst_" + n + " " + mix + ".emptyCountedEnvironment t")
        else:
            parameters = "{Object Agent : Type} (base : " + obj + ".Interpretation Object Agent) (atoms : String → List (String × Object) → Nat → Prop) (t : Nat) "
            premise = obj + ".roleDenote base atoms " + definition_module + ".typedSourceAst " + obj + ".emptyEnvironment t"
            conclusion = (obj + ".roleDenote base atoms " + original + ".typedSourceAst " + obj + ".emptyEnvironment t ↔\n    "
                + obj + ".roleDenote base atoms expandedNormAst_" + n + " " + obj + ".emptyEnvironment t")
        name = "unit_" + n + "_whole_norm_definition_expansion"
        statement = parameters + "(hSourceDefinition : " + premise + ") :\n    " + conclusion
        proof = _reviewed_definition_application_proof(original_expression["root"], expanded["root"], row["target_typed_paths"])
        text += "theorem " + name + " " + statement + " := by\n  exact " + proof + "\n#print axioms " + name + "\n"
        names.append(module + "." + name)
        bindings.append({"theorem": names[-1], "binding": {"kind": "whole_norm_definition_expansion", "unit_id": unit["unit_id"],
            "premise_kind": "independently_denoted_source_definition", "desired_equivalence_hypothesis": False,
            "atom_binding": "canonical_Object_restriction_of_original_mixed_atoms" if is_mixed else "unchanged_original_Object_atoms",
            "definition_typed_expression_sha256": row["definition_typed_expression_sha256"],
            "original_typed_expression_sha256": row["original_typed_expression_sha256"],
            "expanded_typed_expression_sha256": row["expanded_typed_expression_sha256"]}, "declaration": "theorem " + name + " " + statement})
        text += _reviewed_definition_application_abi_example(unit, definition_module)
    return text, names, bindings


def _reviewed_definition_application_pins(owners, definition_application_profile):
    pins = _reviewed_preservation_pins(owners)
    if definition_application_profile is not None:
        from ..syntax_core import algebra, ast
        for module in (algebra, ast):
            path = str(Path(module.__file__).resolve())
            digest = _sha(Path(path).read_bytes())
            if path in pins and pins[path] != digest:
                _fail("definition application canonical AST owner pin collision")
            pins[path] = digest
    return pins


REVIEWED_PHYSICAL_REALIZATION_SCHEMA = "legal-reviewed-physical-definition-realization-preparation/v1"
REVIEWED_PHYSICAL_REALIZATION_PROFILE = "reviewed-unary-object-definition-physical-evidence-realization/v1"

def _reviewed_physical_realization_policy():
    _reviewed_definition_realization_policy()
    if (REVIEWED_PHYSICAL_REALIZATION_SCHEMA, REVIEWED_PHYSICAL_REALIZATION_PROFILE) != (
            "legal-reviewed-physical-definition-realization-preparation/v1",
            "reviewed-unary-object-definition-physical-evidence-realization/v1"):
        _fail("fixed separate physical evidence realization profile required")

def prepare_reviewed_physical_definition_realization_corpus_v1(preservation, graph, admission, *args,
        physical_request_raw, expected_physical_request_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Retain complete reviewed evidence under a separate constructed-model profile.

    The original immutable physical request is required on every replay. Its
    normalized context and digest are bound into the project; the potentially
    large request itself is not copied into generated modules or cache recipes.
    No new legal semantics, external legal dependency or proof is supported.
    """
    if type(physical_request_raw) is not bytes:
        _fail("original immutable physical request bytes required")
    contracts.require_sha256(expected_physical_request_sha256, "physical request SHA256")
    if _sha(physical_request_raw) != expected_physical_request_sha256:
        _fail("original physical request differs from independent pin")
    _reviewed_physical_realization_policy()
    if instance_identity_profile is not None or definition_application_profile is not None:
        _fail("physical realization selected profiles require a separately closed bridge")
    return _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256)

def validate_reviewed_physical_definition_realization_corpus_v1(preparation, preservation, graph, admission, *args,
        physical_request_raw, expected_physical_request_sha256, expected_realization_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Regenerate the complete physical evidence and both project envelopes."""
    if type(physical_request_raw) is not bytes:
        _fail("original immutable physical request bytes required")
    contracts.require_sha256(expected_physical_request_sha256, "physical request SHA256")
    if _sha(physical_request_raw) != expected_physical_request_sha256:
        _fail("original physical request differs from independent pin")
    _reviewed_physical_realization_policy()
    if instance_identity_profile is not None or definition_application_profile is not None:
        _fail("physical realization selected profiles require a separately closed bridge")
    contracts.require_sha256(expected_realization_sha256, "physical realization preparation SHA256")
    if reviewed_preservation_corpus_sha256(preparation) != expected_realization_sha256:
        _fail("complete physical realization preparation differs from independent pin")
    return _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, offered=preparation, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256)

__all__ += ["REVIEWED_PHYSICAL_REALIZATION_SCHEMA", "REVIEWED_PHYSICAL_REALIZATION_PROFILE",
    "prepare_reviewed_physical_definition_realization_corpus_v1",
    "validate_reviewed_physical_definition_realization_corpus_v1"]



REVIEWED_PHYSICAL_REALIZATION_SCHEMA_V2 = "legal-reviewed-physical-definition-realization-preparation/v2"
REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2 = "reviewed-source-use-whole-norm-definition-physical-evidence-realization/v2"


def _reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile):
    if (type(instance_identity_profile) is not str or instance_identity_profile != "reviewed-source-use/v1"
            or type(definition_application_profile) is not str
            or definition_application_profile != "whole-norm-definition-expansion/v1"):
        _fail("explicit joint source-use whole-norm physical bridge required")
    _reviewed_definition_realization_policy(instance_identity_profile=instance_identity_profile,
        definition_application_profile=definition_application_profile)


def _reviewed_physical_realization_policy_v2():
    _reviewed_physical_realization_policy()
    if (REVIEWED_PHYSICAL_REALIZATION_SCHEMA_V2, REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2) != (
            "legal-reviewed-physical-definition-realization-preparation/v2",
            "reviewed-source-use-whole-norm-definition-physical-evidence-realization/v2"):
        _fail("closed joint physical realization V2 profile required")
    _reviewed_joint_physical_profiles_v2("reviewed-source-use/v1", "whole-norm-definition-expansion/v1")


def prepare_reviewed_physical_definition_realization_corpus_v2(preservation, graph, admission, *args,
        physical_request_raw, expected_physical_request_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        instance_identity_profile, definition_application_profile, **kwargs):
    """Construct the complete, source-bound conditional project with physical evidence.

    The physical request contains upstream preservation, not this derived project,
    and confers no Native, legal, training, corpus or release authority.
    """
    _reviewed_physical_realization_policy_v2()
    _reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile)
    return _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256,
        physical_bridge_version=2, instance_identity_profile=instance_identity_profile,
        definition_application_profile=definition_application_profile)


def validate_reviewed_physical_definition_realization_corpus_v2(preparation, preservation, graph, admission, *args,
        physical_request_raw, expected_physical_request_sha256, expected_realization_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain,
        instance_identity_profile, definition_application_profile, **kwargs):
    """Independently regenerate every source, review, physical and project binding."""
    _reviewed_physical_realization_policy_v2()
    _reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile)
    contracts.require_sha256(expected_realization_sha256, "physical realization preparation SHA256")
    if reviewed_preservation_corpus_sha256(preparation) != expected_realization_sha256:
        _fail("complete physical realization preparation differs from independent pin")
    return _reviewed_definition_realization_operation(preservation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, offered=preparation, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256,
        physical_bridge_version=2, instance_identity_profile=instance_identity_profile,
        definition_application_profile=definition_application_profile)


__all__ += ["REVIEWED_PHYSICAL_REALIZATION_SCHEMA_V2", "REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2",
    "prepare_reviewed_physical_definition_realization_corpus_v2",
    "validate_reviewed_physical_definition_realization_corpus_v2"]
