"""Candidate-only V2 conditional Lean projects, with replayed review custody.

No process, toolchain probe, build or admission occurs here. Original combined
review evidence is replayed unchanged; exact native rendering and closed local
project transport are delegated to their existing owners on explicit use.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_definition_use_review_v2 as review

SCHEMA = "legal-corpus-v2-definition-use-lake-preparation/v1"
PROFILE = "replayed-v2-definition-use-conditional-project/v1"
INPUT_BINDING_SCHEMA = "legal-corpus-v2-definition-use-native-input-binding/v1"
PARENT_SCHEMA = "legal-corpus-parent-definition-use-lake-preparation/v1"
PARENT_PROFILE = "replayed-parent-definition-use-conditional-project/v1"
PARENT_INPUT_BINDING_SCHEMA = "legal-corpus-parent-definition-use-native-input-binding/v1"
MAX_INPUT_BYTES = 48 * 1024 * 1024
MAX_PARENT_REPLAY_BYTES = 64 * 1024 * 1024
MAX_PROJECT_BYTES = 8 * 1024 * 1024
MAX_FILES = 9
MAX_EVIDENCE = 256
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+")
_REFUSED = re.compile(r"\b(?:sorry|admit|sorryAx|axiom|unsafe)\b")
REVIEW_INPUT_FIELDS = {
    "subject",
    "registry",
    "policy",
    "reviews",
    "dependency_manifest",
    "component_raw",
    "expected_component_pin",
    "use_inputs",
    "expected_subject_sha256",
    "expected_registry_sha256",
    "expected_policy_sha256",
    "expected_reviews_sha256",
    "expected_manifest_sha256",
    "at_time_utc",
    "observed_artifact_sha256s",
    "observed_pins",
    "evidence_artifacts",
}
FALSE_FLAGS = {
    **review.FALSE_FLAGS,
    **dict.fromkeys(
        (
            "build_eligible",
            "installed_toolchain_verified",
            "toolchain_probed",
            "kernel_proofs_checked",
            "conditional_proofs_verified",
            "native_build_profile_registered",
        ),
        False,
    ),
}
PARENT_FALSE_FLAGS = {**FALSE_FLAGS, **review.PARENT_FALSE_FLAGS}

FIELDS = {
    "profile",
    "toolchain",
    "review_intake_binding",
    "review_evidence_status",
    "review_blockers",
    "review_prerequisites_satisfied_under_selected_trust",
    "review_dependency_manifest",
    "review_source_binding",
    "native_fragments",
    "expected_modules",
    "module_imports",
    "file_sha256",
    "conditional_theorems",
    "theorem_assumptions",
    "producer_pins",
    "native_producer_pins",
    "execution_handoff",
    "preparation_only",
    "lean_compilation_status",
    "proof_status",
    "hash_recipes",
    *FALSE_FLAGS,
}
PARENT_FIELDS = FIELDS | set(PARENT_FALSE_FLAGS)



@dataclass(frozen=True)
class DefinitionUseCorpusPreparation:
    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        raw = self.manifest_json.encode("utf-8")
        return contracts.load_record_bytes(raw, expected_sha256=_sha(raw))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(canonical_dag_json_bytes(value))


def _fail(message):
    raise contracts.CorpusContractError(message)


def _need(value, message):
    if not value:
        _fail(message)


def _pure_pins():
    path = Path(__file__).resolve()
    return {str(path): _sha(path.read_bytes())} | review._pure_pins()


_IMPORTED_PURE_PINS = _pure_pins()
_OPERATION_PINS = None


def _owners():
    from ..formalization.autoencoder import native_family_lean_emitters
    from . import legal_corpus_lake, legal_family_routes

    return legal_family_routes, native_family_lean_emitters, legal_corpus_lake


def _pins(owners):
    global _OPERATION_PINS
    pure = _pure_pins()
    _need(
        pure == _IMPORTED_PURE_PINS,
        "V2 native preparation pure owners changed since import",
    )
    extra = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in owners
    }
    extra.update(owners[0].producer_pins())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(extra)
    _need(
        extra == _OPERATION_PINS,
        "V2 native preparation operation owners changed since first use",
    )
    return pure | extra


def _preflight(
    assessment_raw, expected_assessment_file_sha256, review_inputs, toolchain, *, parent=False
):
    _need(
        _pure_pins() == _IMPORTED_PURE_PINS,
        "V2 native preparation pure owners changed since import",
    )
    _need(
        type(toolchain) is str
        and len(toolchain) <= 128
        and _TOOLCHAIN.fullmatch(toolchain),
        "exact version-pinned Lean toolchain string required",
    )
    review.use._bounded(
        assessment_raw,
        expected_assessment_file_sha256,
        contracts.MAX_RECORD_BYTES,
        "review assessment file",
    )
    contracts.require_keys(
        review_inputs, REVIEW_INPUT_FIELDS, "complete original combined-review inputs"
    )
    if parent:
        parent_preflight = review._preflight(
            review_inputs["component_raw"], review_inputs["expected_component_pin"],
            review_inputs["use_inputs"], parent=True)
    else:
        review._preflight(
            review_inputs["component_raw"],
            review_inputs["expected_component_pin"],
            review_inputs["use_inputs"],
        )
    source = review_inputs["use_inputs"]
    total = len(assessment_raw) + len(review_inputs["component_raw"])
    total += len(
        canonical_dag_json_bytes(
            contracts.clone_json(review_inputs["expected_component_pin"])
        )
    )
    total += sum(
        len(source[label + "_raw"])
        for label in ("request", "registry", "lookup", "query")
    )
    if parent:
        total += sum(endpoint[0] for endpoint in parent_preflight[1]["endpoints"])
    else:
        total += review.use._preflight(source["donor_evidence_inputs"])
        total += review.use._preflight(source["consumer_evidence_inputs"])
    for name in (
        "subject",
        "registry",
        "policy",
        "reviews",
        "dependency_manifest",
        "observed_artifact_sha256s",
        "observed_pins",
    ):
        total += len(
            canonical_dag_json_bytes(contracts.clone_json(review_inputs[name]))
        )
    for name in (
        "expected_subject_sha256",
        "expected_registry_sha256",
        "expected_policy_sha256",
        "expected_reviews_sha256",
        "expected_manifest_sha256",
    ):
        contracts.require_sha256(review_inputs[name], name)
        total += len(review_inputs[name])
    contracts.require_text(
        review_inputs["at_time_utc"], "explicit evaluation time", max_bytes=128
    )
    total += len(review_inputs["at_time_utc"].encode())
    evidence = review_inputs["evidence_artifacts"]
    _need(
        type(evidence) is dict and len(evidence) <= MAX_EVIDENCE,
        "bounded complete review evidence byte population required",
    )
    for name, raw in evidence.items():
        contracts.require_text(name, "review evidence identity", max_bytes=512)
        _need(type(raw) is bytes, "original review evidence bytes required")
        total += len(name.encode()) + len(raw)
    _need(total <= MAX_INPUT_BYTES, "complete native preparation input budget exceeded")


def _module(prefix, identity, *, parent=False):
    return ("LegalCorpusParent." if parent else "LegalCorpusV2.") + prefix + _sha(identity.encode())


def _file(module, imports, body):
    return (
        "\n".join("import " + item for item in imports)
        + "\nnamespace "
        + module
        + "\n"
        + body
        + "\nend "
        + module
        + "\n"
    )


def _fragment_inputs(component, review_inputs, *, parent=False):
    result = []
    source = review_inputs["use_inputs"]
    for role in ("donor", "consumer"):
        evidence = source[role + "_evidence_inputs"]
        report = contracts.load_record_bytes(
            evidence["candidate_inputs"]["report_raw"],
            expected_sha256=evidence["expected_candidate_pin"]["report_sha256"],
        )
        result.append(
            (
                role,
                report["native"],
                _module(
                    "Definition", evidence["expected_candidate_pin"]["candidate_cid"], parent=parent
                ),
            )
        )
    result.extend(
        (role, component[role + "_native"], _module(prefix, identity, parent=parent))
        for role, prefix, identity in (
            ("alias", "Alias", component["binding_record"]["record_cid"]),
            ("joint", "Joint", component["record_cid"]),
        )
    )
    return result


def _render(component, review_inputs, toolchain, binding, owners, *, parent=False):
    routes, emitter, _ = owners
    namespace = "LegalCorpusParent" if parent else "LegalCorpusV2"
    fragments = []
    for role, original, module in _fragment_inputs(component, review_inputs, parent=parent):
        native = routes.prepare_native_fragment(
            family=component["family"],
            formula=original["formula"],
            expected_ast=original["native_ast"],
        )
        _need(
            native == original,
            "native component fragment changed during independent lowering",
        )
        fragments.append({"role": role, "module": module, "native": native})
    by_role = {row["role"]: row for row in fragments}
    donor, consumer, alias, joint = (
        by_role[role]["module"] for role in ("donor", "consumer", "alias", "joint")
    )
    imports = {
        namespace + ".Prelude": [],
        donor: [namespace + ".Prelude"],
        consumer: [namespace + ".Prelude"],
        alias: [donor, consumer],
        joint: [donor, consumer, alias],
        namespace: [joint],
    }
    modules = [namespace + ".Prelude", donor, consumer, alias, joint, namespace]
    _need(len(set(modules)) == 6, "exact distinct native module population required")
    position = {module: index for index, module in enumerate(modules)}
    _need(
        all(
            position[dependency] < position[module]
            for module in modules
            for dependency in imports[module]
        ),
        "closed acyclic native import population required",
    )
    files = {
        "lakefile.toml": ('name = "'
            + ("legal_corpus_parent_definition_use" if parent else "legal_corpus_v2_definition_use")
            + '"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["' + namespace + '"]\n'),
        "lean-toolchain": toolchain + "\n",
        namespace + "/Prelude.lean": "namespace " + namespace + "\n"
        + emitter.PRELUDE
        + "\nend " + namespace + "\n",
        ("parent-input-bindings.json" if parent else "v2-input-bindings.json"): canonical_dag_json_bytes(binding).decode() + "\n",
    }
    for role in ("donor", "consumer"):
        row = by_role[role]
        ast = row["native"]["native_ast"]
        variable = ast["variable"]["name"]
        body = emitter.FormulaRenderer().formula(
            ast["formula"]["right"], {variable: "entity"}
        )
        body = (
            row["native"]["lean_body"]
            + "\ndef bodyAt {Entity Agent : Type} (i : Interpretation Entity Agent) (entity : Entity) : Nat → Prop := "
            + body
        )
        files[row["module"].replace(".", "/") + ".lean"] = _file(
            row["module"], imports[row["module"]], body
        )
    alias_ast = by_role["alias"]["native"]["native_ast"]
    predicate = emitter.FormulaRenderer().formula(
        alias_ast["formula"]["left"], {alias_ast["variable"]["name"]: "entity"}
    )
    alias_body = (
        by_role["alias"]["native"]["lean_body"]
        + "\n"
        + "def consumerPredicateAt {Entity Agent : Type} (i : Interpretation Entity Agent) (entity : Entity) : Nat → Prop := "
        + predicate
        + "\n"
        + "theorem consumer_predicate_iff_donor_body {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (entity : Entity)\n"
        + "    (hDonor : "
        + donor
        + ".formula_0 i t) (hAlias : formula_0 i t) :\n"
        + "    consumerPredicateAt i entity t ↔ "
        + donor
        + ".bodyAt i entity t := by\n"
        + "  exact (hAlias entity).trans (hDonor entity)\n#print axioms consumer_predicate_iff_donor_body"
    )
    files[alias.replace(".", "/") + ".lean"] = _file(alias, imports[alias], alias_body)
    joint_body = (
        by_role["joint"]["native"]["lean_body"]
        + "\n"
        + "def jointAt {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := fun t => "
        + donor
        + ".formula_0 i t ∧ ("
        + consumer
        + ".formula_0 i t ∧ "
        + alias
        + ".formula_0 i t)\n"
        + "theorem joint_of_components {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat)\n"
        + "    (hDonor : "
        + donor
        + ".formula_0 i t) (hConsumer : "
        + consumer
        + ".formula_0 i t)\n"
        + "    (hAlias : "
        + alias
        + ".formula_0 i t) : formula_0 i t := by\n"
        + "  exact And.intro hDonor (And.intro hConsumer hAlias)\n#print axioms joint_of_components\n"
        + "theorem joint_matches_original {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) :\n"
        + "    jointAt i t ↔ formula_0 i t := by\n  exact Iff.rfl\n#print axioms joint_matches_original"
    )
    files[joint.replace(".", "/") + ".lean"] = _file(joint, imports[joint], joint_body)
    files[namespace + ".lean"] = "import " + joint + "\n"
    for module in modules:
        path = module.replace(".", "/") + ".lean"
        actual = re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", files[path])
        _need(
            actual == imports[module] and not _REFUSED.search(files[path]),
            "native module imports or generated keyword contract differs",
        )
    _need(
        len(files) == MAX_FILES
        and sum(len(body.encode()) for body in files.values()) <= MAX_PROJECT_BYTES,
        "complete generated project exceeds profile bounds",
    )
    theorems = [
        alias + ".consumer_predicate_iff_donor_body",
        joint + ".joint_of_components",
        joint + ".joint_matches_original",
    ]
    return files, fragments, modules, imports, theorems


def _prepare_definition_use_corpus(
    assessment_raw, *, expected_assessment_file_sha256, review_inputs, toolchain,
    parent=False, parent_input_sha256=None
):
    """Prepare unqualified candidate text, preserving the replayed review outcome."""
    _preflight(
        assessment_raw, expected_assessment_file_sha256, review_inputs, toolchain, parent=parent
    )
    assessment = contracts.load_record_bytes(
        assessment_raw, expected_sha256=expected_assessment_file_sha256
    )
    validate_review = (review.validate_parent_definition_use_review_assessment_v1 if parent
                       else review.validate_definition_use_review_assessment_v2)
    assessment = validate_review(assessment, **review_inputs)
    owners = _owners()
    producers = _pins(owners)
    component = contracts.load_record_bytes(
        review_inputs["component_raw"],
        expected_sha256=review_inputs["expected_component_pin"]["component_sha256"],
    )
    subject = review_inputs["subject"]
    prep = subject["native_binding"]
    _need(
        component["joint_native"]["native_ast"] == prep["native_ast"],
        "native project must preserve the complete reviewed joint AST",
    )
    binding = contracts.seal_record(
        {
            "schema": PARENT_INPUT_BINDING_SCHEMA if parent else INPUT_BINDING_SCHEMA,
            "profile": PARENT_PROFILE if parent else PROFILE,
            **({"original_input_commitment_sha256": parent_input_sha256} if parent else {}),
            "assessment_file_sha256": expected_assessment_file_sha256,
            "assessment_canonical_sha256": _digest(assessment),
            "assessment_sha256": assessment["assessment_sha256"],
            **{
                name: review_inputs[name]
                for name in (
                    "expected_subject_sha256",
                    "expected_registry_sha256",
                    "expected_policy_sha256",
                    "expected_reviews_sha256",
                    "expected_manifest_sha256",
                )
            },
            "component_pin": review_inputs["expected_component_pin"],
            "review_preparation_cid": prep["record_cid"],
            "combined_scope_cid": subject["scope_id"],
            "evaluation_time_utc": review_inputs["at_time_utc"],
            "observed_artifact_sha256s_sha256": _digest(
                review_inputs["observed_artifact_sha256s"]
            ),
            "observed_pins_sha256": _digest(review_inputs["observed_pins"]),
            "evidence_artifact_sha256s": {
                name: _sha(raw)
                for name, raw in sorted(review_inputs["evidence_artifacts"].items())
            },
        }
    )
    files, fragments, modules, imports, theorems = _render(
        component, review_inputs, toolchain, binding, owners, parent=parent
    )
    manifest = contracts.seal_record(
        {
            "schema": PARENT_SCHEMA if parent else SCHEMA,
            "profile": PARENT_PROFILE if parent else PROFILE,
            "toolchain": toolchain,
            "review_intake_binding": binding,
            "review_evidence_status": assessment["evidence_assessment_status"],
            "review_blockers": assessment["blockers"],
            "review_prerequisites_satisfied_under_selected_trust": assessment[
                "review_prerequisites_satisfied_under_selected_trust"
            ],
            "review_dependency_manifest": review_inputs["dependency_manifest"],
            "review_source_binding": {
                key: prep[key]
                for key in (
                    "original_definitions",
                    "contexts",
                    "binding_record",
                    "alias_record",
                    "scope_binding",
                    "context_slot_ids",
                    "review_contract",
                )
            },
            "native_fragments": fragments,
            "expected_modules": modules,
            "module_imports": imports,
            "file_sha256": {
                name: _sha(body.encode()) for name, body in sorted(files.items())
            },
            "conditional_theorems": theorems,
            "theorem_assumptions": [
                "One supplied Interpretation, Entity carrier and Nat evaluation time are shared by all fragments.",
                "Predicate-to-donor-body equivalence assumes the exact donor definition and explicit alias; neither is proved as a fact.",
                "Joint assembly assumes the exact donor definition, consumer definition and alias.",
                "Modular joint equivalence is a generated definitional obligation; native kernel checking has not run.",
                "No conclusion about the consumer head follows from the donor body without its separate complete Boolean body obligations.",
            ] + ([
                "Both endpoint definitions remain caller interpretations of literal parent text, not authenticated statutory facts.",
                "The cross-parent scope route and alias are caller declarations; matching unknown editions do not establish governing scope or edition compatibility.",
                "Contributor completeness, source-region roles, applicability and complete contextual meaning remain unverified.",
            ] if parent else []),
            "producer_pins": producers,
            "native_producer_pins": fragments[-1]["native"]["producer_pins"],
            "execution_handoff": {
                "status": "parent_build_execution_adapter_not_registered" if parent else "V2_build_execution_adapter_not_registered",
                "target": "legal",
                "argv_recipe": [
                    "<verified-native-lake>",
                    "--offline",
                    "--no-cache",
                    "build",
                    "legal",
                ],
                "expected_olean_paths": [
                    ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean"
                    for module in modules
                ],
                "expected_theorem_axiom_dependencies": {name: [] for name in theorems},
                "observed_theorem_axiom_dependencies": None,
                "installed_binary_pins": None,
                "processes_executed": 0,
                "build_eligible": False,
            },
            "preparation_only": True,
            "lean_compilation_status": "not_run",
            "proof_status": "pending",
            "hash_recipes": {
                "original_assessment_file": "SHA256 of exact original bytes",
                "assessment_internal": "existing review-engine assessment_sha256",
                "canonical_records_and_ASTs": "SHA256 of full canonical DAG JSON",
                "files": "SHA256 of complete generated UTF8 bytes; preparation manifest pinned separately",
                **({"original_parent_input_commitment":
                    "SHA256 streamed typed tree of full original inputs excluding offered output: "
                    "d/l collection tags with decimal child count and colon; sorted dict string keys; "
                    "b/s/i/r scalar tags with decimal byte length, colon and exact bytes/UTF8/decimal-int/finite-JSON-float body; "
                    "n/t/f tags for null/true/false"} if parent else {}),
            },
            **(PARENT_FALSE_FLAGS if parent else FALSE_FLAGS),
        }
    )
    _need(
        _pins(owners) == producers,
        "V2 native preparation producers changed during rendering",
    )
    return DefinitionUseCorpusPreparation(
        canonical_dag_json_bytes(manifest).decode(), tuple(sorted(files.items()))
    )


def prepare_definition_use_corpus_v2(
    assessment_raw, *, expected_assessment_file_sha256, review_inputs, toolchain
):
    """Prepare the unchanged official V2 candidate profile, never parent input."""
    return _prepare_definition_use_corpus(assessment_raw,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)


def validate_definition_use_corpus_v2(preparation, assessment_raw, **validation_inputs):
    _need(
        type(preparation) is DefinitionUseCorpusPreparation,
        "typed V2 native preparation required",
    )
    contracts.validate_record(preparation.to_dict(), schema=SCHEMA, fields=FIELDS)
    expected = prepare_definition_use_corpus_v2(assessment_raw, **validation_inputs)
    _need(
        preparation == expected,
        "V2 native project differs from complete independent regeneration",
    )
    return preparation


def load_definition_use_corpus_v2(
    directory, assessment_raw, *, expected_manifest_sha256, **validation_inputs
):
    expected = prepare_definition_use_corpus_v2(assessment_raw, **validation_inputs)
    transport = _owners()[2]
    files = transport._read_files(
        directory,
        {name for name, _ in expected.files} | {transport.MANIFEST_FILE},
        maximum_files=MAX_FILES,
    )
    raw = files.pop(transport.MANIFEST_FILE)
    contracts.load_record_bytes(raw, expected_sha256=expected_manifest_sha256)
    _need(
        raw == expected.manifest_json.encode()
        and files == {name: body.encode() for name, body in expected.files},
        "V2 native project transport differs from independent preparation",
    )
    return expected


def write_definition_use_corpus_v2(
    preparation, directory, assessment_raw, **validation_inputs
):
    checked = validate_definition_use_corpus_v2(
        preparation, assessment_raw, **validation_inputs
    )
    transport = _owners()[2]

    def readback(root, raw):
        load_definition_use_corpus_v2(
            root,
            assessment_raw,
            expected_manifest_sha256=_sha(raw),
            **validation_inputs,
        )

    return transport._write_project(
        checked, directory, readback=readback, maximum_files=MAX_FILES
    )


class _ParentInputBudget:
    """Bound and detach an expanded mixed caller graph before any body hash."""
    def __init__(self):
        self.remaining = MAX_INPUT_BYTES
        self.nodes = 1_000_000
        self.active = set()

    def charge(self, size):
        _need(size <= self.remaining, "complete parent Lake input budget exceeded")
        self.remaining -= size

    def copy(self, value, depth=0):
        self.nodes -= 1
        _need(self.nodes >= 0 and depth <= 48, "parent Lake input node/depth bound exceeded")
        kind = type(value)
        if kind is bytes:
            self.charge(len(value)); return value
        if kind is str:
            _need(len(value) <= self.remaining, "parent Lake string exceeds remaining input budget")
            try:
                raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (UnicodeError, ValueError) as error:
                _fail("ordinary parent Lake UTF8 string required")
            self.charge(len(raw)); return value
        if value is None or kind is bool:
            self.charge(5); return value
        if kind is int:
            _need(-(2**63) <= value < 2**63, "signed64 parent Lake integer required")
            self.charge(len(str(value))); return value
        if kind is float:
            _need(math.isfinite(value), "finite parent Lake float required")
            self.charge(len(json.dumps(value, allow_nan=False))); return value
        _need(kind in (dict, list), "plain parent Lake JSON or immutable bytes required")
        _need(len(value) <= self.nodes, "parent Lake input collection node bound exceeded")
        identity = id(value)
        _need(identity not in self.active, "cyclic parent Lake input refused")
        self.active.add(identity)
        try:
            self.charge(2 + max(0, len(value) - 1))
            if kind is list:
                return [self.copy(child, depth + 1) for child in value]
            result = {}
            for key, child in value.items():
                _need(type(key) is str and len(key) <= 4096, "bounded plain parent Lake key required")
                self.charge(1)
                result[self.copy(key, depth + 1)] = self.copy(child, depth + 1)
            return result
        finally:
            self.active.remove(identity)


def _emit_parent_replay_value(value, emit):
    """Emit the original typed commitment frames for an already bounded tree."""
    def frame(tag, raw):
        emit(tag + str(len(raw)).encode("ascii") + b":")
        emit(raw)

    def visit(item):
        kind = type(item)
        if kind in (dict, list):
            emit((b"d" if kind is dict else b"l") + str(len(item)).encode("ascii") + b":")
            if kind is dict:
                for key in sorted(item):
                    visit(key); visit(item[key])
            else:
                for child in item:
                    visit(child)
        elif kind is bytes:
            frame(b"b", item)
        elif kind is str:
            frame(b"s", item.encode("utf-8"))
        elif item is None:
            emit(b"n")
        elif kind is bool:
            emit(b"t" if item else b"f")
        elif kind is int:
            frame(b"i", str(item).encode("ascii"))
        elif kind is float:
            frame(b"r", json.dumps(item, allow_nan=False).encode("ascii"))
        else:
            _fail("bounded parent commitment scalar required")

    visit(value)


def _parent_commitment(value):
    """Stream the unchanged typed tree after its complete input bound passed.

    Each collection has its tag and decimal child count followed by a colon;
    dict keys are sorted and emitted as strings before their values. Each
    byte/string/int/float scalar has its tag, decimal raw length, colon and raw
    body. Null/true/false are distinct one-byte tags. No tagged copy or complete
    serialized tree is allocated. This commitment grants no evidence authority.
    """
    hasher = hashlib.sha256()
    _emit_parent_replay_value(value, hasher.update)
    return hasher.hexdigest()


def _parent_replay_maximum(max_bytes):
    _need(type(max_bytes) is int and 1 <= max_bytes <= MAX_PARENT_REPLAY_BYTES,
          "parent replay byte maximum must be an integer from one through 64 MiB")
    return max_bytes


def encode_parent_replay_value_v1(value, *, max_bytes=MAX_PARENT_REPLAY_BYTES):
    """Encode a detached ordinary tree with the original typed commitment frames.

    The existing complete expanded-input budget is applied before any emission;
    the independent wire bound is checked before every output buffer growth.
    These bytes transport caller evidence and grant no validation authority.
    """
    maximum = _parent_replay_maximum(max_bytes)
    detached = _ParentInputBudget().copy(value)
    output = bytearray()

    def emit(raw):
        _need(len(raw) <= maximum - len(output), "parent replay payload byte bound exceeded")
        output.extend(raw)

    _emit_parent_replay_value(detached, emit)
    return bytes(output)


class _ParentReplayValueDecoder:
    """Bounded parser for the original typed frames, never arbitrary objects."""
    def __init__(self, payload, maximum):
        self.payload = payload
        self.view = memoryview(payload)
        self.maximum = maximum
        self.position = 0
        self.budget = _ParentInputBudget()

    def header(self, limit):
        start = self.position
        number = 0
        while True:
            _need(self.position < len(self.payload), "truncated parent replay header")
            byte = self.payload[self.position]
            if byte == 58:
                _need(self.position > start, "empty parent replay header")
                self.position += 1
                return number
            _need(48 <= byte <= 57, "decimal parent replay header required")
            _need(self.position == start or self.payload[start] != 48,
                  "leading zero in parent replay header")
            digit = byte - 48
            _need(number <= (limit - digit) // 10, "parent replay header bound exceeded")
            number = number * 10 + digit
            self.position += 1

    def body_end(self, length):
        _need(length <= len(self.payload) - self.position, "truncated parent replay body")
        return self.position + length

    def scalar(self, tag, *, key):
        limit = self.maximum
        if key:
            limit = min(limit, 4 * 4096)
        elif tag == 105:
            limit = min(limit, 20)
        elif tag == 114:
            limit = min(limit, 32)
        length = self.header(limit)
        start = self.position
        end = self.body_end(length)
        if tag == 115:
            # JSON ensure_ascii=False retains UTF8 and adds quotes/escapes.
            # Charge that exact expanded cost before slicing or decoding a body.
            self.budget.charge(length + 2)
            extra = 0
            for byte in self.view[start:end]:
                if byte in (34, 92, 8, 9, 10, 12, 13):
                    extra += 1
                elif byte < 32:
                    extra += 5
                _need(extra <= self.budget.remaining,
                      "complete parent Lake input budget exceeded")
            self.budget.charge(extra)
            try:
                result = self.payload[start:end].decode("utf-8")
            except UnicodeError:
                _fail("ordinary parent replay UTF8 string required")
            _need(not key or len(result) <= 4096, "bounded plain parent Lake key required")
        else:
            self.budget.charge(length)
            raw = self.payload[start:end]
            if tag == 98:
                result = raw
            elif tag == 105:
                _need(re.fullmatch(rb"-?(?:0|[1-9][0-9]*)", raw) is not None,
                      "canonical parent replay integer required")
                result = int(raw)
                _need(-(2**63) <= result < 2**63 and raw == str(result).encode("ascii"),
                      "signed64 canonical parent replay integer required")
            else:
                try:
                    result = float(raw)
                except (ValueError, OverflowError):
                    _fail("canonical finite parent replay float required")
                _need(math.isfinite(result) and
                      raw == json.dumps(result, allow_nan=False).encode("ascii"),
                      "canonical finite parent replay float required")
        self.position = end
        return result

    def value(self, depth=0, *, key=False):
        self.budget.nodes -= 1
        _need(self.budget.nodes >= 0 and depth <= 48,
              "parent Lake input node/depth bound exceeded")
        _need(self.position < len(self.payload), "truncated parent replay value")
        tag = self.payload[self.position]
        self.position += 1
        _need(not key or tag == 115, "plain parent replay string key required")
        if tag in (98, 115, 105, 114):
            return self.scalar(tag, key=key)
        if tag in (110, 116, 102):
            self.budget.charge(5)
            return None if tag == 110 else tag == 116
        _need(tag in (100, 108), "unsupported parent replay tag")
        count = self.header(self.budget.nodes)
        _need(count <= self.budget.nodes // (2 if tag == 100 else 1),
              "parent Lake input collection node bound exceeded")
        self.budget.charge(2 + max(0, count - 1))
        if tag == 108:
            result = []
            for _ in range(count):
                result.append(self.value(depth + 1))
            return result
        result = {}
        previous = None
        for _ in range(count):
            self.budget.charge(1)
            name = self.value(depth + 1, key=True)
            _need(previous is None or previous < name,
                  "sorted unique parent replay dictionary keys required")
            previous = name
            result[name] = self.value(depth + 1)
        return result

    def canonical(self, value):
        position = 0

        def compare(raw):
            nonlocal position
            end = position + len(raw)
            _need(end <= len(self.payload) and self.view[position:end] == raw,
                  "canonical parent replay encoding required")
            position = end

        _emit_parent_replay_value(value, compare)
        _need(position == len(self.payload), "canonical complete parent replay encoding required")


def decode_parent_replay_value_v1(payload, *, expected_payload_sha256,
                                  max_bytes=MAX_PARENT_REPLAY_BYTES):
    """Decode only bounded canonical typed bytes under an independent SHA256.

    Nodes, nesting, scalar expansion and keys are charged while parsing, before
    body allocation or collection growth. The returned tree contains only plain
    dict/list/string/bytes/int/float/bool/None values, never replay capabilities.
    """
    maximum = _parent_replay_maximum(max_bytes)
    _need(type(payload) is bytes and 0 < len(payload) <= maximum,
          "bounded immutable nonempty parent replay bytes required")
    _need(type(expected_payload_sha256) is str and
          re.fullmatch(r"[0-9a-f]{64}", expected_payload_sha256) is not None,
          "independent lowercase SHA256 parent replay pin required")
    _need(_sha(payload) == expected_payload_sha256, "parent replay payload SHA256 mismatch")
    parser = _ParentReplayValueDecoder(payload, maximum)
    result = parser.value()
    _need(parser.position == len(payload), "trailing parent replay bytes refused")
    parser.canonical(result)
    return result


def _parent_offered(preparation):
    _need(type(preparation) is DefinitionUseCorpusPreparation,
          "typed parent definition-use preparation required")
    text, files = preparation.manifest_json, preparation.files
    _need(type(text) is str and type(files) is tuple and len(files) == MAX_FILES,
          "closed parent preparation manifest/nine-file storage required")
    result = []
    for item in files:
        _need(type(item) is tuple and len(item) == 2 and all(type(value) is str for value in item),
              "plain parent preparation file pairs required")
        result.append(list(item))
    return {"manifest_json": text, "files": result}


def _parent_capture(assessment_raw, expected_assessment_file_sha256, review_inputs, toolchain, offered=None):
    _need(type(assessment_raw) is bytes and 0 < len(assessment_raw) <= contracts.MAX_RECORD_BYTES,
          "bounded immutable parent assessment bytes required")
    _need(type(review_inputs) is dict and len(review_inputs) == len(REVIEW_INPUT_FIELDS)
          and all(type(key) is str for key in review_inputs) and set(review_inputs) == REVIEW_INPUT_FIELDS,
          "closed complete parent combined-review inputs required")
    graph = {"assessment_raw": assessment_raw, "expected_assessment_file_sha256": expected_assessment_file_sha256,
        "review_inputs": review_inputs, "toolchain": toolchain,
        "offered": None if offered is None else _parent_offered(offered)}
    copied = _ParentInputBudget().copy(graph)
    frozen = _parent_commitment(copied)
    base = {key: value for key, value in copied.items() if key != "offered"}
    return copied, frozen, _parent_commitment(base)


def _parent_fence(original, copied, frozen, offered=None):
    _need(_parent_capture(**original, offered=offered)[1] == frozen,
          "caller parent Lake input or offered preparation changed")
    detached = {key: copied[key] for key in original}
    # The original offered object is separately fenced; retain its detached JSON
    # in the second complete root without constructing a public capability.
    graph = {**detached, "offered": copied["offered"]}
    snapshot = _ParentInputBudget().copy(graph)
    _need(_parent_commitment(snapshot) == frozen,
          "detached parent Lake inputs changed")


def _parent_operation(original, operation, offered=None):
    copied, frozen, commitment = _parent_capture(**original, offered=offered)
    failure = None
    try:
        return operation(copied, commitment)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _parent_fence(original, copied, frozen, offered)
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing parent Lake input comparison also failed.")


def prepare_parent_definition_use_corpus_v1(
    assessment_raw, *, expected_assessment_file_sha256, review_inputs, toolchain
):
    """Replay literal-parent combined review and prepare conditional text only."""
    original = dict(assessment_raw=assessment_raw,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    def prepare(copied, commitment):
        return _prepare_definition_use_corpus(copied["assessment_raw"],
            expected_assessment_file_sha256=copied["expected_assessment_file_sha256"],
            review_inputs=copied["review_inputs"], toolchain=copied["toolchain"],
            parent=True, parent_input_sha256=commitment)
    return _parent_operation(original, prepare)


def _validate_parent(preparation, copied, commitment):
    manifest = contracts.load_record_bytes(copied["offered"]["manifest_json"].encode("utf-8"),
        expected_sha256=_sha(copied["offered"]["manifest_json"].encode("utf-8")))
    contracts.validate_record(manifest, schema=PARENT_SCHEMA, fields=PARENT_FIELDS)
    expected = _prepare_definition_use_corpus(copied["assessment_raw"],
        expected_assessment_file_sha256=copied["expected_assessment_file_sha256"],
        review_inputs=copied["review_inputs"], toolchain=copied["toolchain"],
        parent=True, parent_input_sha256=commitment)
    _need(copied["offered"] == _parent_offered(expected),
          "parent native project differs from complete independent regeneration")
    return expected


def validate_parent_definition_use_corpus_v1(preparation, assessment_raw, **validation_inputs):
    original = dict(assessment_raw=assessment_raw, **validation_inputs)
    return _parent_operation(original,
        lambda copied, commitment: _validate_parent(preparation, copied, commitment), preparation)


def load_parent_definition_use_corpus_v1(directory, assessment_raw, *, expected_manifest_sha256, **validation_inputs):
    original = dict(assessment_raw=assessment_raw, **validation_inputs)
    def load(copied, commitment):
        expected = _prepare_definition_use_corpus(copied["assessment_raw"],
            expected_assessment_file_sha256=copied["expected_assessment_file_sha256"],
            review_inputs=copied["review_inputs"], toolchain=copied["toolchain"],
            parent=True, parent_input_sha256=commitment)
        transport = _owners()[2]
        files = transport._read_files(directory,
            {name for name, _ in expected.files} | {transport.MANIFEST_FILE}, maximum_files=MAX_FILES)
        raw = files.pop(transport.MANIFEST_FILE)
        contracts.load_record_bytes(raw, expected_sha256=expected_manifest_sha256)
        _need(raw == expected.manifest_json.encode()
              and files == {name: body.encode() for name, body in expected.files},
              "parent project transport differs from independent preparation")
        return expected
    return _parent_operation(original, load)


def write_parent_definition_use_corpus_v1(preparation, directory, assessment_raw, **validation_inputs):
    original = dict(assessment_raw=assessment_raw, **validation_inputs)
    def write(copied, commitment):
        checked = _validate_parent(preparation, copied, commitment)
        transport = _owners()[2]
        def readback(root, raw):
            return load_parent_definition_use_corpus_v1(root, copied["assessment_raw"],
                expected_manifest_sha256=_sha(raw),
                **{key: copied[key] for key in validation_inputs})
        return transport._write_project(checked, directory, readback=readback, maximum_files=MAX_FILES)
    return _parent_operation(original, write, preparation)


__all__ = [
    "DefinitionUseCorpusPreparation",
    "prepare_definition_use_corpus_v2",
    "validate_definition_use_corpus_v2",
    "write_definition_use_corpus_v2",
    "load_definition_use_corpus_v2",
    "prepare_parent_definition_use_corpus_v1",
    "validate_parent_definition_use_corpus_v1",
    "write_parent_definition_use_corpus_v1",
    "load_parent_definition_use_corpus_v1",
]


# A separate bounded profile keeps complete relational norms beside conditional
# exact-occurrence definitions.  It never widens the existing V2/parent routes.
BOUND_NORM_SCHEMA = "legal-corpus-bound-norm-definition-lake-preparation/v1"
BOUND_NORM_PROFILE = "replayed-bound-norm-definition-conditional-project/v1"
BOUND_NORM_INPUT_BINDING_SCHEMA = "legal-corpus-bound-norm-definition-input-binding/v1"
BOUND_NORM_FALSE_FLAGS = {
    **FALSE_FLAGS,
    **dict.fromkeys(("norm_truth_proved", "definition_applied_to_norm",
        "membership_assumption_verified", "source_adoption_verified",
        "governing_definition_use_verified"), False),
}
_BOUND_NORM_INPUT_FIELDS = {
    "bound_report", "expected_bound_report_sha256", "bound_definition_inputs", "toolchain"
}
_BOUND_DEFINITION_INPUT_FIELDS = {
    "companion", "request_raw", "expected_companion_sha256",
    "expected_request_sha256", "companion_inputs",
}
_BOUND_NORM_NAMESPACE = "LegalCorpusBoundNormDefinition"
_BOUND_NORM_OPERATION_PINS = None


def _bound_norm_storage(preparation):
    _need(type(preparation) is DefinitionUseCorpusPreparation,
          "typed bound norm definition preparation required")
    data = object.__getattribute__(preparation, "__dict__")
    _need(type(data) is dict and set(data) == {"manifest_json", "files"},
          "closed bound norm definition preparation storage required")
    offered = _parent_offered(preparation)
    text = offered["manifest_json"]
    _need(0 < len(text) <= contracts.MAX_RECORD_BYTES,
          "bounded bound norm definition manifest required")
    try:
        raw = text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("ordinary bound norm definition manifest UTF8 required") from error
    _need(len(raw) <= contracts.MAX_RECORD_BYTES,
          "bound norm definition manifest byte bound exceeded")
    names, total = [], 0
    for name, body in offered["files"]:
        _need(len(name) <= 256
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name)
              and all(part not in (".", "..") for part in name.split("/")),
              "closed two-level bound norm project path required")
        _need("\x00" not in body and len(body) <= MAX_PROJECT_BYTES,
              "bounded ordinary bound norm project source required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("ordinary bound norm project UTF8 required") from error
        _need(total <= MAX_PROJECT_BYTES, "complete bound norm project byte bound exceeded")
        names.append(name)
    _need(names == sorted(set(names)), "distinct sorted bound norm project files required")
    return offered


def bound_norm_definition_preparation_sha256(preparation):
    """Commit the full parsed manifest and all nine file texts, not authority.

    The wire recipe is the existing native owner's preparation commitment:
    compact sorted ordinary UTF8 JSON of {manifest: object, files: pairs}.
    """
    offered = _bound_norm_storage(preparation)
    raw = offered["manifest_json"].encode("utf-8")
    manifest = contracts.load_record_bytes(raw, expected_sha256=_sha(raw))
    document = {"manifest": manifest, "files": offered["files"]}
    _ParentInputBudget().copy(document)
    wire = json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(wire) <= 20 * 1024 * 1024,
          "complete bound norm native preparation commitment exceeds 20 MiB")
    return _sha(wire)


def _bound_norm_capture(original, offered=None):
    _need(type(original) is dict and set(original) == _BOUND_NORM_INPUT_FIELDS,
          "closed bound norm definition preparation inputs required")
    _need(type(original["bound_report"]) is dict,
          "complete original bound-variable report required")
    inputs = original["bound_definition_inputs"]
    _need(type(inputs) is dict and set(inputs) == _BOUND_DEFINITION_INPUT_FIELDS,
          "complete original bound-variable replay inputs required")
    contracts.require_sha256(original["expected_bound_report_sha256"],
                             "independent complete bound-variable report")
    toolchain = original["toolchain"]
    _need(type(toolchain) is str and len(toolchain) <= 128
          and _TOOLCHAIN.fullmatch(toolchain), "exact version-pinned Lean toolchain required")
    graph = {**original, "offered": None if offered is None else _bound_norm_storage(offered)}
    copied = _ParentInputBudget().copy(graph)
    base = {key: value for key, value in copied.items() if key != "offered"}
    return copied, _parent_commitment(copied), _parent_commitment(base)


def _bound_norm_pins(bound, owners):
    global _BOUND_NORM_OPERATION_PINS
    pure = _pure_pins()
    _need(pure == _IMPORTED_PURE_PINS, "bound norm pure producers changed since import")
    observed = dict(pure)
    sources = [bound._pins(bound._owners()), owners[0].producer_pins()]
    sources.append({str(Path(module.__file__).resolve()):
                    _sha(Path(module.__file__).read_bytes()) for module in (bound, *owners)})
    for source in sources:
        for path, pin in source.items():
            _need(path not in observed or observed[path] == pin,
                  "bound norm producer observations disagree")
            observed[path] = pin
    if _BOUND_NORM_OPERATION_PINS is None:
        _BOUND_NORM_OPERATION_PINS = dict(observed)
    _need(observed == _BOUND_NORM_OPERATION_PINS,
          "bound norm producers changed since first use")
    return observed


def _bound_norm_operation(original, operation, offered=None):
    _need(_pure_pins() == _IMPORTED_PURE_PINS,
          "bound norm pure producers changed since import")
    copied, commitment, base_commitment = _bound_norm_capture(original, offered)
    from . import legal_bound_variable_definition_v1 as bound
    _need(bound.bound_variable_definition_sha256(copied["bound_report"])
          == copied["expected_bound_report_sha256"],
          "independent complete bound-variable report pin differs")
    # This is the existing pure preflight.  Full endpoint/source replay follows
    # only after complete input bounds and independent commitments pass.
    bound._preflight(copied["bound_definition_inputs"])
    owners = _owners()
    pins = _bound_norm_pins(bound, owners)

    def fence():
        _need(_bound_norm_capture(original, offered)[1] == commitment,
              "caller bound norm project inputs changed during operation")
        _need(_parent_commitment(_ParentInputBudget().copy(copied)) == commitment,
              "detached bound norm project inputs changed during operation")
        _need(_bound_norm_pins(bound, owners) == pins,
              "bound norm project producers changed during operation")

    failure = None
    try:
        fence()
        return operation(copied, base_commitment, bound, owners, pins, fence)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing bound norm Lake input or producer comparison also failed.")


def _render_bound_norm_definition(checked, norm, toolchain, binding, owners):
    routes, emitter, _ = owners
    namespace = _BOUND_NORM_NAMESPACE
    norm_native = routes.prepare_native_fragment(family="deontic_fol",
        formula=norm["native_formula"], expected_ast=norm["native_ast"])
    _need(norm_native == norm["native_fragment"]
          and norm_native["lean_body"] == norm["lean_body"],
          "complete original norm native rendering changed")
    source = checked["lean_source"]
    prefix = "namespace LegalBoundVariableDefinition\n" + emitter.PRELUDE + "\n"
    suffix = "end LegalBoundVariableDefinition\n"
    _need(source.startswith(prefix) and source.endswith(suffix),
          "exact original bound-variable source framing required")
    body = source[len(prefix):-len(suffix)]
    marker = "\ntheorem definition_instance "
    _need(body.count(marker) == 1, "one original conditional theorem boundary required")
    definition_body, tail = body.split(marker, 1)
    theorem_body = "theorem definition_instance " + tail
    definition_native = checked["definition_native_fragment"]
    _need(definition_body.startswith(definition_native["lean_body"] + "\n"),
          "whole original definition native body must remain exact")
    norm_module = namespace + ".Norm_" + _digest({
        "native": norm_native, "original_norm": checked["original_norm"],
        "input": binding["original_input_commitment_sha256"]})
    definition_module = namespace + ".Definition_" + _digest(definition_native)
    occurrence_module = namespace + ".Occurrence_" + binding["bound_definition_report_sha256"]
    preservation_module = namespace + ".Preservation_" + _digest(binding)
    prelude = namespace + ".Prelude"
    modules = [prelude, norm_module, definition_module, occurrence_module,
               preservation_module, namespace]
    imports = {prelude: [], norm_module: [prelude], definition_module: [prelude],
        occurrence_module: [norm_module, definition_module],
        preservation_module: [norm_module, occurrence_module], namespace: [preservation_module]}
    _need(len(set(modules)) == 6, "six distinct bound norm modules required")
    position = {name: index for index, name in enumerate(modules)}
    _need(all(position[dependency] < position[name] for name in modules
              for dependency in imports[name]), "closed acyclic bound norm import population required")
    files = {
        "lakefile.toml": 'name = "legal_corpus_bound_norm_definition"\nversion = "0.1.0"\n\n'
            '[[lean_lib]]\nname = "legal"\nroots = ["' + namespace + '"]\n',
        "lean-toolchain": toolchain + "\n",
        "bound-norm-input-bindings.json": canonical_dag_json_bytes(binding).decode() + "\n",
        prelude.replace(".", "/") + ".lean": "namespace " + namespace + "\n"
            + emitter.PRELUDE + "\nend " + namespace + "\n",
        norm_module.replace(".", "/") + ".lean": _file(norm_module, imports[norm_module],
                                                          norm_native["lean_body"]),
        definition_module.replace(".", "/") + ".lean": _file(definition_module,
            imports[definition_module], definition_body),
        occurrence_module.replace(".", "/") + ".lean": _file(occurrence_module,
            imports[occurrence_module], "open " + definition_module + "\n" + theorem_body),
        preservation_module.replace(".", "/") + ".lean": _file(preservation_module,
            imports[preservation_module],
            "def originalNormAt {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := "
            + norm_module + ".formula_0 i\n"
            + "theorem original_norm_preserved {Entity Agent : Type} "
            + "(i : Interpretation Entity Agent) (t : Nat) :\n"
            + "    originalNormAt i t ↔ " + norm_module + ".formula_0 i t := by\n"
            + "  exact Iff.rfl\n#print axioms original_norm_preserved\n"),
        namespace + ".lean": "import " + preservation_module + "\n",
    }
    source_map = []
    for original in checked["conditional_theorems"]:
        _need(original.startswith("LegalBoundVariableDefinition."),
              "original bound theorem namespace differs")
        source_map.append({"original": original,
                           "project": occurrence_module + "." + original.rsplit(".", 1)[1]})
    theorems = [row["project"] for row in source_map] + [preservation_module + ".original_norm_preserved"]
    _need(len(theorems) in (2, 3), "two or three explicit conditional obligations required")
    for module in modules:
        actual = re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$",
                            files[module.replace(".", "/") + ".lean"])
        _need(actual == imports[module] and not _REFUSED.search(
            files[module.replace(".", "/") + ".lean"]),
            "bound norm generated imports or keyword contract differs")
    _need(len(files) == MAX_FILES
          and sum(len(text.encode("utf-8")) for text in files.values()) <= MAX_PROJECT_BYTES,
          "complete bound norm project storage bound exceeded")
    fragments = [{"role": "norm", "module": norm_module, "native": norm_native},
                 {"role": "definition", "module": definition_module, "native": definition_native}]
    source_binding = {"original_lean_source_sha256": _sha(source.encode()),
        "definition_body_sha256": _sha(definition_body.encode()),
        "conditional_theorem_body_sha256": _sha(theorem_body.encode()),
        "original_namespace": "LegalBoundVariableDefinition", "theorem_names": source_map,
        "namespace_packaging_only": True, "norm_body_byte_exact": True,
        "definition_applied_to_norm": False, "norm_driven_membership_inferred": False}
    return files, fragments, modules, imports, theorems, source_binding


def _prepare_bound_norm_definition(copied, input_commitment, bound, owners, pins, fence):
    checked = bound.validate_bound_variable_definition_v1(copied["bound_report"],
        expected_report_sha256=copied["expected_bound_report_sha256"],
        **copied["bound_definition_inputs"])
    fence()
    inputs = copied["bound_definition_inputs"]["companion_inputs"]
    preparation = inputs["norm_preparation"]
    norm = preparation["correspondence"]["relational_fragment"]
    norm_digest = bound.evidence.norm.norm_review_sha256
    original = checked["original_norm"]
    _need(original["unchanged"] is True
          and original["preparation_sha256"] == inputs["expected_norm_preparation_sha256"]
          and original["correspondence_sha256"] == preparation["correspondence_sha256"]
          and original["ast_sha256"] == norm_digest(norm["typed_expression"])
          and original["native_ast_sha256"] == norm_digest(norm["native_ast"]),
          "complete original norm/AST/correspondence commitments differ")
    _need(norm["source_binding"] is None and norm["source_bound"] is False,
          "original relational source-binding scope must remain unchanged")
    binding = contracts.seal_record({"schema": BOUND_NORM_INPUT_BINDING_SCHEMA,
        "profile": BOUND_NORM_PROFILE, "original_input_commitment_sha256": input_commitment,
        "bound_definition_report_sha256": copied["expected_bound_report_sha256"],
        "bound_definition_request_sha256": checked["request_sha256"],
        "companion_sha256": checked["companion_sha256"], "original_norm": original,
        "source_context_sha256": norm_digest(copied["bound_definition_inputs"]["companion"]["source_context"]),
        "selected_link_sha256": norm_digest(checked["selected_link"]),
        "occurrence_binding_sha256": norm_digest(checked["occurrence_binding"]),
        "definition_alternatives_sha256": norm_digest(checked["definition_alternatives"]),
        "nomination_inventory_sha256": norm_digest(checked["nomination_inventory"]),
        "bound_definition_mode": checked["request"]["mode"]})
    files, fragments, modules, imports, theorems, source_binding = _render_bound_norm_definition(
        checked, norm, copied["toolchain"], binding, owners)
    fence()
    manifest = contracts.seal_record({"schema": BOUND_NORM_SCHEMA, "profile": BOUND_NORM_PROFILE,
        "toolchain": copied["toolchain"], "review_intake_binding": binding,
        "original_input_commitment_sha256": input_commitment,
        "bound_definition_report_sha256": copied["expected_bound_report_sha256"],
        "original_norm": original, "occurrence_binding": checked["occurrence_binding"],
        "selected_link": checked["selected_link"],
        "definition_alternatives": checked["definition_alternatives"],
        "nomination_inventory": checked["nomination_inventory"],
        "bound_definition_mode": checked["request"]["mode"],
        "conditional_source_binding": source_binding,
        "review_evidence_status": "unsigned_pending_source_meaning_and_applicability",
        "review_blockers": copied["bound_definition_inputs"]["companion"]["norm_obligations"],
        "review_prerequisites_satisfied_under_selected_trust": False,
        "native_fragments": fragments, "expected_modules": modules,
        "module_imports": imports,
        "file_sha256": {name: _sha(text.encode()) for name, text in sorted(files.items())},
        "conditional_theorems": theorems,
        "theorem_assumptions": [
            "One arbitrary Entity carrier, Interpretation and fixed Nat time are shared by the exact original norm and definition modules.",
            "The conditional definition instance assumes hDefinition; deriving its body additionally assumes hMembership at the same supplied entity valuation.",
            "No existential witness, actual membership, governing applicability, source meaning or norm truth is inferred.",
            "The complete supplied norm AST and native body are unchanged. The preservation obligation is only a definitional alias identity, not a source-meaning theorem.",
            "No definition is substituted into a predicate, quantifier or modality of the norm; all original alternatives and nominations remain retained.",
        ],
        "producer_pins": pins, "native_producer_pins": fragments[0]["native"]["producer_pins"],
        "execution_handoff": {"status": "bound_norm_build_execution_adapter_not_registered",
            "target": "legal", "argv_recipe": ["<verified-native-lake>", "--offline", "--no-cache", "build", "legal"],
            "expected_olean_paths": [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules],
            "expected_theorem_axiom_dependencies": {name: [] for name in theorems},
            "observed_theorem_axiom_dependencies": None, "installed_binary_pins": None,
            "processes_executed": 0, "build_eligible": False},
        "input_budget": {"bytes": MAX_INPUT_BYTES, "expanded_values": 1_000_000, "depth": 48},
        "preparation_only": True, "lean_compilation_status": "not_run", "proof_status": "pending",
        "authority": dict(bound.AUTHORITY), "native_ast_rewritten": False,
        "norm_interpretation_ready": False, "selected_interpretation": None,
        "governing_definition_use": None, "training_mask": 0, "evaluation_gold_mask": 0,
        "external_complete_inputs_required": True,
        **BOUND_NORM_FALSE_FLAGS})
    result = DefinitionUseCorpusPreparation(canonical_dag_json_bytes(manifest).decode(),
                                             tuple(sorted(files.items())))
    bound_norm_definition_preparation_sha256(result)
    fence()
    return result


def prepare_bound_norm_definition_corpus_v1(bound_report, *, expected_bound_report_sha256,
        bound_definition_inputs, toolchain):
    """Prepare one unchanged complete relational norm and conditional definition.

    This bounded sibling profile executes no build and supplies no source,
    membership, governing-definition, review, graph or corpus authority.
    """
    original = dict(bound_report=bound_report, expected_bound_report_sha256=expected_bound_report_sha256,
                    bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    return _bound_norm_operation(original, _prepare_bound_norm_definition)


def _validate_bound_norm_definition(preparation, copied, commitment, expected, bound, owners, pins, fence):
    contracts.require_sha256(expected, "independent full bound norm preparation")
    _need(bound_norm_definition_preparation_sha256(preparation) == expected,
          "independent complete bound norm preparation pin differs")
    checked = _prepare_bound_norm_definition(copied, commitment, bound, owners, pins, fence)
    _need(copied["offered"] == _bound_norm_storage(checked),
          "bound norm project differs from complete original-input regeneration")
    return checked


def validate_bound_norm_definition_corpus_v1(preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256,
        bound_definition_inputs, toolchain):
    contracts.require_sha256(expected_preparation_sha256, "independent full bound norm preparation")
    _need(bound_norm_definition_preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete bound norm preparation pin differs")
    original = dict(bound_report=bound_report, expected_bound_report_sha256=expected_bound_report_sha256,
                    bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    def validate(copied, commitment, bound, owners, pins, fence):
        return _validate_bound_norm_definition(preparation, copied, commitment,
            expected_preparation_sha256, bound, owners, pins, fence)
    return _bound_norm_operation(original, validate, preparation)


def load_bound_norm_definition_corpus_v1(directory, bound_report, *, expected_manifest_sha256,
        expected_preparation_sha256, expected_bound_report_sha256, bound_definition_inputs, toolchain):
    contracts.require_sha256(expected_manifest_sha256, "independent bound norm project manifest")
    contracts.require_sha256(expected_preparation_sha256, "independent complete bound norm preparation")
    original = dict(bound_report=bound_report, expected_bound_report_sha256=expected_bound_report_sha256,
                    bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    def load(copied, commitment, bound, owners, pins, fence):
        expected = _prepare_bound_norm_definition(copied, commitment, bound, owners, pins, fence)
        _need(bound_norm_definition_preparation_sha256(expected) == expected_preparation_sha256,
              "independent bound norm project commitment differs")
        transport = owners[2]
        files = transport._read_files(directory,
            {name for name, _ in expected.files} | {transport.MANIFEST_FILE}, maximum_files=MAX_FILES)
        raw = files.pop(transport.MANIFEST_FILE)
        contracts.load_record_bytes(raw, expected_sha256=expected_manifest_sha256)
        _need(raw == expected.manifest_json.encode()
              and files == {name: text.encode() for name, text in expected.files},
              "bound norm project transport differs from complete regeneration")
        fence()
        return expected
    return _bound_norm_operation(original, load)


def write_bound_norm_definition_corpus_v1(preparation, directory, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256, bound_definition_inputs, toolchain):
    contracts.require_sha256(expected_preparation_sha256, "independent full bound norm preparation")
    _need(bound_norm_definition_preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete bound norm preparation pin differs")
    original = dict(bound_report=bound_report, expected_bound_report_sha256=expected_bound_report_sha256,
                    bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    def write(copied, commitment, bound, owners, pins, fence):
        checked = _validate_bound_norm_definition(preparation, copied, commitment,
            expected_preparation_sha256, bound, owners, pins, fence)
        def readback(root, raw):
            load_bound_norm_definition_corpus_v1(root, copied["bound_report"],
                expected_manifest_sha256=_sha(raw), expected_preparation_sha256=expected_preparation_sha256,
                expected_bound_report_sha256=copied["expected_bound_report_sha256"],
                bound_definition_inputs=copied["bound_definition_inputs"], toolchain=copied["toolchain"])
        result = owners[2]._write_project(checked, directory, readback=readback, maximum_files=MAX_FILES)
        fence()
        return result
    return _bound_norm_operation(original, write, preparation)


__all__ += [
    "prepare_bound_norm_definition_corpus_v1", "validate_bound_norm_definition_corpus_v1",
    "load_bound_norm_definition_corpus_v1", "write_bound_norm_definition_corpus_v1",
    "bound_norm_definition_preparation_sha256",
]


# Explicit complete authored norm project over genuine decoded-parent custody.
# This sibling does not widen the HTML/definition-use/bound-definition profiles.
PARENT_NORM_SCHEMA = "legal-corpus-parent-norm-lake-preparation/v1"
PARENT_NORM_PROFILE = "replayed-parent-literal-complete-authored-norm-project/v1"
PARENT_NORM_INPUT_BINDING_SCHEMA = "legal-corpus-parent-norm-input-binding/v1"
_PARENT_NORM_NAMESPACE = "LegalCorpusParentNorm"
_PARENT_NORM_INPUT_FIELDS = {"correspondence", "expected_correspondence_sha256",
                             "correspondence_inputs", "toolchain"}
_PARENT_NORM_REPLAY_FIELDS = {"scope_report", "relational_report", "mapping_request_raw",
    "expected_scope_report_sha256", "expected_relational_report_sha256",
    "expected_mapping_request_sha256", "scope_replay_inputs", "relational_request_raw",
    "expected_relational_request_sha256"}
PARENT_NORM_FALSE_FLAGS = {**FALSE_FLAGS, **dict.fromkeys((
    "source_bound", "source_meaning_verified", "source_edition_verified",
    "source_region_complete", "definition_applied_to_norm", "membership_assumption_verified",
    "governing_definition_use_verified", "norm_truth_proved", "semantic_graph_admitted",
    "Lean_admitted", "model_executed", "training_executed"), False)}
_PARENT_NORM_OPERATION_PINS = None


def _parent_norm_storage(preparation):
    _need(type(preparation) is DefinitionUseCorpusPreparation,
          "typed parent norm preparation required")
    data = object.__getattribute__(preparation, "__dict__")
    _need(type(data) is dict and set(data) == {"manifest_json", "files"},
          "closed parent norm preparation storage required")
    text, files = data["manifest_json"], data["files"]
    _need(type(text) is str and 0 < len(text) <= contracts.MAX_RECORD_BYTES
          and type(files) is tuple and len(files) == 7,
          "bounded parent norm manifest and exactly seven files required")
    try:
        _need(len(text.encode("utf-8")) <= contracts.MAX_RECORD_BYTES,
              "parent norm manifest byte bound exceeded")
    except UnicodeError:
        _fail("ordinary parent norm manifest UTF8 required")
    result, names, total = [], [], 0
    for pair in files:
        _need(type(pair) is tuple and len(pair) == 2
              and all(type(value) is str for value in pair), "ordinary parent norm file pair required")
        name, body = pair
        _need(len(name) <= 256
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name)
              and all(part not in (".", "..") for part in name.split("/"))
              and "\x00" not in body and len(body) <= MAX_PROJECT_BYTES,
              "closed bounded parent norm project path/source required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError:
            _fail("ordinary parent norm project UTF8 required")
        _need(total <= MAX_PROJECT_BYTES, "complete parent norm project byte bound exceeded")
        names.append(name); result.append([name, body])
    _need(names == sorted(set(names)), "distinct sorted parent norm files required")
    return {"manifest_json": text, "files": result}


def parent_norm_preparation_sha256(preparation):
    """Commit complete parsed manifest and all seven files; grant no proof authority."""
    storage = _parent_norm_storage(preparation)
    raw = storage["manifest_json"].encode("utf-8")
    manifest = contracts.load_record_bytes(raw, expected_sha256=_sha(raw))
    _need(manifest.get("schema") == PARENT_NORM_SCHEMA and manifest.get("profile") == PARENT_NORM_PROFILE,
          "explicit parent norm preparation schema/profile required")
    document = {"manifest": manifest, "files": storage["files"]}
    _ParentInputBudget().copy(document)
    wire = json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(wire) <= 20 * 1024**2, "complete parent norm preparation commitment exceeds 20 MiB")
    return _sha(wire)


def _parent_norm_capture(original, offered=None):
    _need(type(original) is dict and set(original) == _PARENT_NORM_INPUT_FIELDS,
          "closed complete parent norm preparation inputs required")
    _need(type(original["correspondence"]) is dict
          and type(original["correspondence_inputs"]) is dict
          and set(original["correspondence_inputs"]) == _PARENT_NORM_REPLAY_FIELDS,
          "complete original parent correspondence and nine-field replay required")
    contracts.require_sha256(original["expected_correspondence_sha256"],
                             "independent complete parent correspondence")
    toolchain = original["toolchain"]
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "exact version-pinned Lean toolchain required")
    graph = {**original, "offered": None if offered is None else _parent_norm_storage(offered)}
    copied = _ParentInputBudget().copy(graph)
    base = {key: value for key, value in copied.items() if key != "offered"}
    return copied, _parent_commitment(copied), _parent_commitment(base)


def _parent_norm_pins(correspondence, owners):
    global _PARENT_NORM_OPERATION_PINS
    pure = _pure_pins()
    _need(pure == _IMPORTED_PURE_PINS, "parent norm pure producers changed since import")
    from . import legal_producer_lineage as lineage
    pins = dict(pure)
    sources = [correspondence._parent_correspondence_pins(correspondence._owners()),
               owners[0].producer_pins()]
    sources.append({str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
                    for module in (correspondence, lineage, lineage.provenance, *owners)})
    for source in sources:
        for path, pin in source.items():
            _need(path not in pins or pins[path] == pin, "parent norm producer observations disagree")
            pins[path] = pin
    if _PARENT_NORM_OPERATION_PINS is None:
        _PARENT_NORM_OPERATION_PINS = dict(pins)
    _need(pins == _PARENT_NORM_OPERATION_PINS, "parent norm producers changed since first use")
    return pins


def _parent_norm_preflight(copied, correspondence):
    """Check independent complete original commitments before operation replay."""
    replay = copied["correspondence_inputs"]
    request = correspondence._parse(replay["mapping_request_raw"],
        replay["expected_mapping_request_sha256"], request_schema=correspondence.REQUEST_SCHEMA_V2)
    scope, relational = correspondence._owners()  # Standard-library-only public owners.
    relational_request = relational._parse(replay["relational_request_raw"],
                                           replay["expected_relational_request_sha256"])
    for field in ("expected_scope_report_sha256", "expected_relational_report_sha256"):
        contracts.require_sha256(replay[field], "independent complete " + field)
    _need(request["scope_report_sha256"] == replay["expected_scope_report_sha256"]
          and request["relational_report_sha256"] == replay["expected_relational_report_sha256"],
          "mapping must bind independently pinned parent scope and relational reports")
    snapshot, commitments = correspondence._parent_correspondence_snapshot(
        replay["scope_report"], replay["relational_report"], replay["scope_replay_inputs"], scope)
    _need(commitments["scope_report"]["sha256"] == replay["expected_scope_report_sha256"]
          and commitments["relational_report"]["sha256"] == replay["expected_relational_report_sha256"],
          "independent complete parent scope or relational report pin differs")
    _need(sum(row["bytes"] for row in commitments.values()) + len(replay["mapping_request_raw"])
          + len(replay["relational_request_raw"]) <= correspondence.MAX_TOTAL_BYTES,
          "aggregate complete parent correspondence original input bound exceeded")
    _need(snapshot["scope_report"].get("schema") == scope.PARENT_SCHEMA
          and snapshot["scope_report"].get("profile") == scope.PARENT_PROFILE,
          "explicit parent literal scope required before operation replay")
    return {"mapping_request": request, "relational_request": relational_request,
            "snapshot": snapshot, "commitments": commitments}


def _parent_norm_file_plan(replay):
    """Select only genuinely replayed parent/cache witnesses, never offered paths."""
    from . import legal_producer_lineage as lineage
    inputs = replay["scope_replay_inputs"]["replay_inputs"]
    manifest = inputs["lineage_inputs"]["witness_manifest"]
    sources = [(inputs["parent_text_views_inputs"]["parent_descriptor"], lineage.MAX_FILE_BYTES)]
    sources += [(row["descriptor"], lineage.MAX_FILE_BYTES) for row in manifest["parents"]]
    for report in manifest["reports"]:
        sources.extend(((report, lineage.MAX_REPORT_BYTES),
                        (report["origin"]["container"], lineage.MAX_REPORT_BYTES)))
    # Cache rows are closed original values; their supplied physical backing is
    # the retained producer JSON and original artifact container above. Catalog
    # source bytes remain independent physical evidence, never executed here.
    for report in inputs["provenance_reports"]:
        for pin in report["catalog_source_pins"]:
            sources.append(({"local_path": pin["path"], "sha256": pin["source_sha256"],
                             "bytes": Path(pin["path"]).lstat().st_size},
                            lineage.provenance.MAX_SOURCE_BYTES))
    by_path = {}
    for source, maximum in sources:
        descriptor = {key: source[key] for key in ("local_path", "sha256", "bytes")}
        previous = by_path.get(descriptor["local_path"])
        _need(previous is None or previous["descriptor"] == descriptor,
              "original parent/cache physical witnesses disagree")
        by_path[descriptor["local_path"]] = {"descriptor": descriptor,
            "maximum": maximum if previous is None else min(maximum, previous["maximum"])}
    _need(bool(by_path) and len(by_path) <= 1 + lineage.MAX_PARENT_FILES
          + 2 * lineage.MAX_REPORTS + lineage.MAX_RECORDS * lineage.provenance.MAX_SOURCES,
          "bounded complete parent/cache physical witness population required")
    return [by_path[path] for path in sorted(by_path)]


def _parent_norm_file_witness(plan):
    """Reuse complete pinned file hashing and FD/path custody without decoding."""
    from . import legal_producer_lineage as lineage
    identities = []
    for item in plan:
        with lineage._opened(item["descriptor"], item["maximum"]) as stream:
            observed = lineage.os.fstat(stream.fileno())
            identities.append([observed.st_dev, observed.st_ino, observed.st_mode,
                observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns])
    return identities


def _parent_norm_callbacks(correspondence, owners):
    from . import legal_producer_lineage as lineage
    scope, relational = correspondence._owners()
    functions = (correspondence.validate_norm_scope_correspondence_v2,
        correspondence.prepare_norm_scope_correspondence_v2,
        correspondence.norm_scope_correspondence_sha256, correspondence._parent_correspondence_snapshot,
        correspondence._parent_correspondence_pins, correspondence._wire,
        correspondence._owners, correspondence._parse, correspondence._raw,
        scope._parent_snapshot, scope._load, relational._parse, relational._pairs,
        lineage._opened, lineage._opened.__wrapped__, lineage._need,
        lineage.os.open, lineage.os.fdopen, lineage.os.fstat,
        scope.validate_parent_norm_scope_v1, scope._parent_finish, scope._parent_serialized_fence,
        relational.validate_relational_norm_v1, relational.prepare_relational_norm_v1,
        owners[0].prepare_native_fragment, owners[0].producer_pins,
        contracts.seal_record, contracts.load_record_bytes, canonical_dag_json_bytes,
        _ParentInputBudget.copy, _parent_commitment, _file, _parent_norm_capture,
        _parent_norm_pins, _parent_norm_preflight, _parent_norm_file_plan,
        _parent_norm_file_witness, _parent_norm_callbacks, _parent_norm_runtime,
        _render_parent_norm, _parent_norm_storage, _parent_norm_serialized_fence,
        parent_norm_preparation_sha256, _parent_norm_operation,
        prepare_parent_norm_corpus_v1, validate_parent_norm_corpus_v1,
        DefinitionUseCorpusPreparation.to_dict)
    return tuple((function, getattr(function, "__code__", None),
                  id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
                 for function in functions)


def _parent_norm_runtime(owners):
    from . import legal_producer_lineage as lineage
    return {"schema": PARENT_NORM_SCHEMA, "profile": PARENT_NORM_PROFILE,
        "binding_schema": PARENT_NORM_INPUT_BINDING_SCHEMA, "namespace": _PARENT_NORM_NAMESPACE,
        "authority": dict(PARENT_NORM_FALSE_FLAGS), "prelude": owners[1].PRELUDE,
        "input_bytes": MAX_INPUT_BYTES, "project_bytes": MAX_PROJECT_BYTES,
        "record_bytes": contracts.MAX_RECORD_BYTES, "input_nodes": 1_000_000, "depth": 48,
        "input_fields": sorted(_PARENT_NORM_INPUT_FIELDS), "replay_fields": sorted(_PARENT_NORM_REPLAY_FIELDS),
        "toolchain_pattern": _TOOLCHAIN.pattern, "refused_pattern": _REFUSED.pattern,
        "parent_file_bytes": lineage.MAX_FILE_BYTES, "producer_report_bytes": lineage.MAX_REPORT_BYTES,
        "catalog_source_bytes": lineage.provenance.MAX_SOURCE_BYTES,
        "parent_files": lineage.MAX_PARENT_FILES, "producer_reports": lineage.MAX_REPORTS,
        "cache_records": lineage.MAX_RECORDS, "catalog_sources": lineage.provenance.MAX_SOURCES}


def _parent_norm_serialized_fence(preparation, expected_storage):
    _need(_parent_norm_storage(preparation) == expected_storage,
          "parent norm preparation changed after final serialization")


def _render_parent_norm(correspondence, norm_native, toolchain, binding, owners):
    namespace = _PARENT_NORM_NAMESPACE
    identity = _digest(binding)
    prelude, norm_module, preservation = (namespace + ".Prelude", namespace + ".Norm_" + identity,
                                         namespace + ".Preservation_" + identity)
    modules = [prelude, norm_module, preservation, namespace]
    imports = {prelude: [], norm_module: [prelude], preservation: [norm_module], namespace: [preservation]}
    theorem = preservation + ".original_norm_preserved"
    body = ("def originalNormAt {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := "
        + norm_module + ".formula_0 i\n"
        + "theorem original_norm_preserved {Entity Agent : Type} "
        + "(i : Interpretation Entity Agent) (t : Nat) :\n"
        + "    originalNormAt i t ↔ " + norm_module + ".formula_0 i t := by\n"
        + "  exact Iff.rfl\n#print axioms original_norm_preserved\n")
    files = {
        "lakefile.toml": 'name = "legal_corpus_parent_norm"\nversion = "0.1.0"\n\n'
            '[[lean_lib]]\nname = "legal"\nroots = ["' + namespace + '"]\n',
        "lean-toolchain": toolchain + "\n",
        "parent-norm-input-bindings.json": canonical_dag_json_bytes(binding).decode("utf-8") + "\n",
        prelude.replace(".", "/") + ".lean": "namespace " + namespace + "\n"
            + owners[1].PRELUDE + "\nend " + namespace + "\n",
        norm_module.replace(".", "/") + ".lean": _file(norm_module, imports[norm_module], norm_native["lean_body"]),
        preservation.replace(".", "/") + ".lean": _file(preservation, imports[preservation], body),
        namespace + ".lean": "import " + preservation + "\n",
    }
    _need(len(files) == 7 and len(set(modules)) == 4
          and sum(len(text.encode("utf-8")) for text in files.values()) <= MAX_PROJECT_BYTES,
          "exact bounded four-module/seven-file parent norm project required")
    position = {module: index for index, module in enumerate(modules)}
    for module in modules:
        text = files[module.replace(".", "/") + ".lean"]
        _need(re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", text) == imports[module]
              and all(position[dependency] < position[module] for dependency in imports[module])
              and not _REFUSED.search(text), "closed acyclic parent norm imports and safe source required")
    return files, modules, imports, [theorem], [{"role": "norm", "module": norm_module, "native": norm_native}]


def _parent_norm_operation(original, offered=None, expected_preparation_sha256=None):
    copied, commitment, base_commitment = _parent_norm_capture(original, offered)
    if offered is not None:
        contracts.require_sha256(expected_preparation_sha256, "independent complete parent norm preparation")
        _need(parent_norm_preparation_sha256(offered) == expected_preparation_sha256,
              "independent complete parent norm preparation pin differs")
    from . import legal_norm_scope_correspondence_v1 as correspondence
    _need(copied["correspondence"].get("schema") == correspondence.SCHEMA_V2
          and copied["correspondence"].get("profile") == "parent-literal-occurrence-authored-correspondence/v2",
          "explicit genuine parent correspondence v2 required, never HTML relabeling")
    _need(correspondence.norm_scope_correspondence_sha256(copied["correspondence"])
          == copied["expected_correspondence_sha256"], "independent complete parent correspondence pin differs")
    preflight = _parent_norm_preflight(copied, correspondence)
    owners = _owners()
    pins = _parent_norm_pins(correspondence, owners)
    callbacks = _parent_norm_callbacks(correspondence, owners)
    runtime = _ParentInputBudget().copy(_parent_norm_runtime(owners))
    held = []
    state = {"opened": None, "closed": None, "native": None, "preparation": None, "storage": None,
             "physical_plan": None, "physical_witness": None}
    started = False
    primary = None

    def hold(value, label):
        snapshot = _parent_commitment(_ParentInputBudget().copy(value))
        held.append((value, snapshot, label))
        return value

    hold(preflight, "pure independently pinned original requests and reports")

    def fence():
        _need(_parent_norm_capture(original, offered)[1] == commitment,
              "original parent norm input or offered preparation changed")
        _need(_parent_commitment(_ParentInputBudget().copy(copied)) == commitment,
              "detached parent norm inputs changed")
        _need(_parent_norm_callbacks(correspondence, owners) == callbacks,
              "parent norm operation callable changed")
        _need(_parent_norm_runtime(owners) == runtime, "parent norm runtime declarations changed")
        _need(_parent_norm_pins(correspondence, owners) == pins, "parent norm source producer changed")
        for value, snapshot, label in held:
            _need(_parent_commitment(_ParentInputBudget().copy(value)) == snapshot,
                  "retained parent norm return changed: " + label)
        if state["physical_plan"] is not None:
            _need(_parent_norm_file_witness(state["physical_plan"]) == state["physical_witness"],
                  "original parent/cache physical file witness changed")
        if state["preparation"] is not None:
            _need(_parent_norm_storage(state["preparation"]) == state["storage"],
                  "parent norm preparation changed after genuine serialized storage check")

    def closing():
        if started:
            fence()
            closed = correspondence.validate_norm_scope_correspondence_v2(copied["correspondence"],
                expected_report_sha256=copied["expected_correspondence_sha256"],
                **copied["correspondence_inputs"])
            state["closed"] = hold(closed, "closing genuine parent correspondence")
            if state["opened"] is not None:
                _need(_parent_commitment(closed) == _parent_commitment(state["opened"]),
                      "closing genuine parent correspondence differs from opening")

    def final_storage():
        if state["preparation"] is not None:
            _parent_norm_serialized_fence(state["preparation"], state["storage"])

    try:
        fence()
        started = True
        checked = correspondence.validate_norm_scope_correspondence_v2(copied["correspondence"],
            expected_report_sha256=copied["expected_correspondence_sha256"],
            **copied["correspondence_inputs"])
        state["opened"] = hold(checked, "opening genuine parent correspondence")
        _need(_parent_commitment(checked) == _parent_commitment(copied["correspondence"]),
              "genuine parent correspondence differs from offered original")
        fence()  # Original/detached/actual-return guards precede path nomination.
        state["physical_plan"] = hold(_parent_norm_file_plan(copied["correspondence_inputs"]),
                                      "complete genuine parent/cache physical plan")
        state["physical_witness"] = hold(_parent_norm_file_witness(state["physical_plan"]),
                                         "opening complete parent/cache file identities")
        fence()
        norm = checked["relational_fragment"]
        _need(norm["source_binding"] is None and norm["source_bound"] is False
              and all(value is False for value in checked["authority"].values())
              and all(type(checked[key]) is int and checked[key] == 0
                      for key in ("training_mask", "evaluation_gold_mask")),
              "original null relational source binding and unsigned parent authority required")
        native = owners[0].prepare_native_fragment(family="deontic_fol",
            formula=norm["native_formula"], expected_ast=norm["native_ast"])
        state["native"] = hold(native, "genuine complete original native fragment")
        _need(native == norm["native_fragment"] and native["lean_body"] == norm["lean_body"],
              "complete original parent norm native rendering changed")
        fence()
        context = checked["source_scope"]["source_context_record"]
        original_norm = {"relational_report_sha256": checked["input_pins"]["relational_report_sha256"],
            "typed_expression_sha256": norm["typed_expression_sha256"],
            "native_ast_sha256": _digest(norm["native_ast"]),
            "native_fragment_sha256": _digest(native), "lean_body_sha256": _sha(native["lean_body"].encode("utf-8")),
            "source_binding": None, "source_bound": False, "unchanged": True}
        binding = hold(contracts.seal_record({"schema": PARENT_NORM_INPUT_BINDING_SCHEMA,
            "profile": PARENT_NORM_PROFILE, "original_input_commitment_sha256": base_commitment,
            "correspondence_sha256": copied["expected_correspondence_sha256"],
            "parent_source_binding_sha256": _digest(checked["source_scope"]["parent_source_binding"]),
            "source_scope_sha256": checked["input_pins"]["scope_report_sha256"],
            "mapping_request_raw_sha256": checked["input_pins"]["mapping_request_raw_sha256"],
            "original_norm": original_norm}), "sealed parent norm input binding")
        files, modules, imports, theorems, fragments = _render_parent_norm(
            checked, native, copied["toolchain"], binding, owners)
        hold(files, "rendered parent norm project files")
        fence()
        manifest = contracts.seal_record({"schema": PARENT_NORM_SCHEMA, "profile": PARENT_NORM_PROFILE,
            "toolchain": copied["toolchain"], "review_intake_binding": binding,
            "original_input_commitment_sha256": base_commitment,
            "correspondence": checked, "correspondence_sha256": copied["expected_correspondence_sha256"],
            "parent_source_binding_sha256": binding["parent_source_binding_sha256"], "original_norm": original_norm,
            "original_parent_context": context, "declared_semantic_coverage": checked["declared_semantic_coverage"],
            "review_blockers": {"missing_context": context["missing_requirements"],
                                "unresolved": checked["retained_unresolved"]},
            "native_fragments": fragments, "expected_modules": modules, "module_imports": imports,
            "file_sha256": {name: _sha(text.encode("utf-8")) for name, text in sorted(files.items())},
            "conditional_theorems": theorems,
            "theorem_assumptions": [
                "The complete supplied authored relational AST and native body are unchanged, with O/P/F as separate uninterpreted parameters.",
                "The preservation theorem is only a definitional alias identity, not a proof of the norm or its source meaning.",
                "No definition is applied, no membership or governing applicability is inferred, and all source/context/edition issues remain open."],
            "producer_pins": pins, "native_producer_pins": native["producer_pins"],
            "execution_handoff": {"status": "parent_norm_execution_adapter_not_registered", "target": "legal",
                "argv_recipe": ["<verified-native-lake>", "--offline", "--no-cache", "build", "legal"],
                "expected_olean_paths": [".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" for module in modules],
                "expected_theorem_axiom_dependencies": {theorem: [] for theorem in theorems},
                "observed_theorem_axiom_dependencies": None, "installed_binary_pins": None,
                "processes_executed": 0, "build_eligible": False},
            "input_budget": {"bytes": MAX_INPUT_BYTES, "expanded_values": 1_000_000, "depth": 48},
            "preparation_only": True, "lean_compilation_status": "not_run", "proof_status": "pending",
            "authority": dict(PARENT_NORM_FALSE_FLAGS), "native_ast_rewritten": False,
            "norm_interpretation_ready": False, "selected_interpretation": None,
            "governing_definition_use": None, "training_mask": 0, "evaluation_gold_mask": 0,
            "external_complete_inputs_required": True, **PARENT_NORM_FALSE_FLAGS})
        hold(manifest, "sealed complete parent norm manifest")
        text = canonical_dag_json_bytes(manifest).decode("utf-8")
        result = DefinitionUseCorpusPreparation(text, tuple(sorted(files.items())))
        state["preparation"] = result
        state["storage"] = _ParentInputBudget().copy(_parent_norm_storage(result))
        parent_norm_preparation_sha256(result)
        if offered is not None:
            _need(copied["offered"] == state["storage"],
                  "parent norm preparation differs from complete original regeneration")
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        scope = correspondence._owners()[0]
        scope._parent_finish((fence, closing, fence, final_storage, fence,
                              final_storage, fence), primary)


def prepare_parent_norm_corpus_v1(correspondence, *, expected_correspondence_sha256,
                                  correspondence_inputs, toolchain):
    """Prepare one complete authored norm project with original parent custody.

    This never classifies a source region, accepts legal meaning, applies a
    definition, writes files, probes a toolchain or executes a native process.
    """
    original = dict(correspondence=correspondence, expected_correspondence_sha256=expected_correspondence_sha256,
                    correspondence_inputs=correspondence_inputs, toolchain=toolchain)
    return _parent_norm_operation(original)


def validate_parent_norm_corpus_v1(preparation, correspondence, *, expected_preparation_sha256,
        expected_correspondence_sha256, correspondence_inputs, toolchain):
    """Regenerate the complete explicit parent norm project from original inputs."""
    original = dict(correspondence=correspondence, expected_correspondence_sha256=expected_correspondence_sha256,
                    correspondence_inputs=correspondence_inputs, toolchain=toolchain)
    return _parent_norm_operation(original, preparation, expected_preparation_sha256)


__all__ += ["PARENT_NORM_SCHEMA", "PARENT_NORM_PROFILE", "PARENT_NORM_FALSE_FLAGS",
    "prepare_parent_norm_corpus_v1", "validate_parent_norm_corpus_v1", "parent_norm_preparation_sha256"]
