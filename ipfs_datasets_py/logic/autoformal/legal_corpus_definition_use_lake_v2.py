"""Candidate-only V2 conditional Lean projects, with replayed review custody.

No process, toolchain probe, build or admission occurs here. Original combined
review evidence is replayed unchanged; exact native rendering and closed local
project transport are delegated to their existing owners on explicit use.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_definition_use_review_v2 as review

SCHEMA = "legal-corpus-v2-definition-use-lake-preparation/v1"
PROFILE = "replayed-v2-definition-use-conditional-project/v1"
INPUT_BINDING_SCHEMA = "legal-corpus-v2-definition-use-native-input-binding/v1"
MAX_INPUT_BYTES = 48 * 1024 * 1024
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
    assessment_raw, expected_assessment_file_sha256, review_inputs, toolchain
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


def _module(prefix, identity):
    return "LegalCorpusV2." + prefix + _sha(identity.encode())


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


def _fragment_inputs(component, review_inputs):
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
                    "Definition", evidence["expected_candidate_pin"]["candidate_cid"]
                ),
            )
        )
    result.extend(
        (role, component[role + "_native"], _module(prefix, identity))
        for role, prefix, identity in (
            ("alias", "Alias", component["binding_record"]["record_cid"]),
            ("joint", "Joint", component["record_cid"]),
        )
    )
    return result


def _render(component, review_inputs, toolchain, binding, owners):
    routes, emitter, _ = owners
    fragments = []
    for role, original, module in _fragment_inputs(component, review_inputs):
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
        "LegalCorpusV2.Prelude": [],
        donor: ["LegalCorpusV2.Prelude"],
        consumer: ["LegalCorpusV2.Prelude"],
        alias: [donor, consumer],
        joint: [donor, consumer, alias],
        "LegalCorpusV2": [joint],
    }
    modules = ["LegalCorpusV2.Prelude", donor, consumer, alias, joint, "LegalCorpusV2"]
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
        "lakefile.toml": 'name = "legal_corpus_v2_definition_use"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCorpusV2"]\n',
        "lean-toolchain": toolchain + "\n",
        "LegalCorpusV2/Prelude.lean": "namespace LegalCorpusV2\n"
        + emitter.PRELUDE
        + "\nend LegalCorpusV2\n",
        "v2-input-bindings.json": canonical_dag_json_bytes(binding).decode() + "\n",
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
    files["LegalCorpusV2.lean"] = "import " + joint + "\n"
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


def prepare_definition_use_corpus_v2(
    assessment_raw, *, expected_assessment_file_sha256, review_inputs, toolchain
):
    """Prepare unqualified candidate text, preserving the replayed review outcome."""
    _preflight(
        assessment_raw, expected_assessment_file_sha256, review_inputs, toolchain
    )
    assessment = contracts.load_record_bytes(
        assessment_raw, expected_sha256=expected_assessment_file_sha256
    )
    assessment = review.validate_definition_use_review_assessment_v2(
        assessment, **review_inputs
    )
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
            "schema": INPUT_BINDING_SCHEMA,
            "profile": PROFILE,
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
        component, review_inputs, toolchain, binding, owners
    )
    manifest = contracts.seal_record(
        {
            "schema": SCHEMA,
            "profile": PROFILE,
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
            ],
            "producer_pins": producers,
            "native_producer_pins": fragments[-1]["native"]["producer_pins"],
            "execution_handoff": {
                "status": "V2_build_execution_adapter_not_registered",
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
            },
            **FALSE_FLAGS,
        }
    )
    _need(
        _pins(owners) == producers,
        "V2 native preparation producers changed during rendering",
    )
    return DefinitionUseCorpusPreparation(
        canonical_dag_json_bytes(manifest).decode(), tuple(sorted(files.items()))
    )


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


__all__ = [
    "DefinitionUseCorpusPreparation",
    "prepare_definition_use_corpus_v2",
    "validate_definition_use_corpus_v2",
    "write_definition_use_corpus_v2",
    "load_definition_use_corpus_v2",
]
