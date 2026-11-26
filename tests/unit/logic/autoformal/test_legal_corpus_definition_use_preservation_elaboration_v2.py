"""Pure elaboration preparation from genuinely replayed synthetic packets.

Retained tool claims and compiled artifacts in these fixtures are synthetic.
The existing public packet and typed lineage validators run unmocked. These
tests establish preparation integrity, never native acceptance or proof.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_v2 as owner
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_native_v2 as elaboration_native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_native_v2 as native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_theorem_lineage_v2 as lineage_owner
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.common import duckdb_proof_store
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, IRClaim
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ProofReceipt


_SPEC = importlib.util.spec_from_file_location(
    "_genuine_preservation_elaboration_lineage_fixtures",
    Path(__file__).with_name("test_legal_corpus_definition_use_preservation_theorem_lineage_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _FIXTURE
_SPEC.loader.exec_module(_FIXTURE)
_PACKETS = _FIXTURE._FIXTURE


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def seal(value):
    return contracts.seal_record({key: item for key, item in value.items()
                                  if key not in {"record_cid", "cid_scope"}})


def manifest(preparation):
    return json.loads(preparation.manifest_json)


def reseal(preparation, document, files=None):
    changed_files = preparation.files if files is None else files
    return replace(preparation, manifest_json=canonical(seal(document)).decode("utf-8"),
                   files=changed_files)


def preparation_pin(preparation):
    # Compute the documented envelope commitment directly so refusal tests
    # reach the public validator, including when its digest helper rejects.
    return sha(canonical({"manifest_json": preparation.manifest_json,
                          "files": [list(pair) for pair in preparation.files]}))


@pytest.fixture(scope="module")
def packets():
    return {family: _PACKETS.synthetic_packet(family) for family in ("fol", "tdfol")}


@pytest.fixture(scope="module")
def arguments(packets):
    return {
        family: _PACKETS.arguments(packet) | {
            "expected_packet_observation_sha256": sha(_PACKETS.read(packet).observation_json.encode()),
        }
        for family, packet in packets.items()
    }


@pytest.fixture(scope="module")
def lineages(packets, arguments):
    return {family: _FIXTURE.prepare(packet, arguments[family])
            for family, packet in packets.items()}


@pytest.fixture(scope="module")
def preparation_arguments(arguments, lineages):
    return {family: values | {"expected_lineage_sha256": lineage_owner.lineage_sha256(lineages[family])}
            for family, values in arguments.items()}


@pytest.fixture(scope="module")
def preparations(packets, lineages, preparation_arguments):
    return {family: prepare(lineages[family], packet, preparation_arguments[family])
            for family, packet in packets.items()}


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("pure elaboration preparation reached execution, a compiler, proof issuance, model or database")
    monkeypatch.setattr(native, "build_definition_use_preservation_native_v2", forbidden)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native, "_binary_recheck", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(process, "_linux_owned_identity", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(BackendRequest, "for_claim", forbidden)
    monkeypatch.setattr(ProofReceipt, "issue", forbidden)
    monkeypatch.setattr(duckdb_proof_store.DuckDBProofStore, "put", forbidden)
    class DenyExecutionImport:
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == name or fullname.startswith(name + ".")
                   for name in ("duckdb", "torch", "transformers")):
                forbidden()
    deny = DenyExecutionImport()
    sys.meta_path.insert(0, deny)
    yield
    sys.meta_path.remove(deny)


def prepare(lineage, packet, arguments, **overrides):
    return owner.prepare_definition_use_preservation_elaboration_v2(
        lineage, packet.files, packet.data["corpus_preparation"], packet.data["assessment_raw"],
        **(arguments | overrides),
    )


def validate(preparation, lineage, packet, arguments, **overrides):
    return owner.validate_definition_use_preservation_elaboration_v2(
        preparation, lineage, packet.files,
        packet.data["corpus_preparation"], packet.data["assessment_raw"],
        **(arguments | {"expected_elaboration_preparation_sha256":
                       preparation_pin(preparation)} | overrides),
    )


def test_public_import_is_stdlib_only():
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','multiformats','pyarrow','duckdb','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_elaboration_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in sys.argv[2:]:
    assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    contracts_to_check = (
        (owner, ("prepare_definition_use_preservation_elaboration_v2",
                 "validate_definition_use_preservation_elaboration_v2", "elaboration_preparation_sha256")),
        (elaboration_native, ("validate_definition_use_preservation_elaboration_native_v2",
                              "build_definition_use_preservation_elaboration_native_v2")),
    )
    for module, public_names in contracts_to_check:
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, module.__file__, *public_names],
                                capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_public_preparation_and_validation_are_deterministic_and_pure(
    family, packets, lineages, preparation_arguments, preparations, no_execution,
):
    original = preparations[family]
    assert owner.elaboration_preparation_sha256(original) == preparation_pin(original)
    assert prepare(lineages[family], packets[family], preparation_arguments[family]) == original
    assert validate(original, lineages[family], packets[family], preparation_arguments[family]) == original


@pytest.mark.parametrize("field", ("expected_lineage_sha256", "expected_packet_observation_sha256"))
def test_wrong_independent_identity_refuses(field, packets, lineages, preparation_arguments, no_execution):
    with pytest.raises(ValueError):
        prepare(lineages["fol"], packets["fol"], preparation_arguments["fol"], **{field: "0" * 64})


def test_wrong_independent_preparation_pin_refuses(
    packets, lineages, preparation_arguments, preparations, no_execution,
):
    with pytest.raises(ValueError):
        validate(preparations["fol"], lineages["fol"], packets["fol"], preparation_arguments["fol"],
                 expected_elaboration_preparation_sha256="0" * 64)


@pytest.mark.parametrize("damage", ("foreign_lineage", "mutable_claims", "cross_family", "typed_zero"))
def test_full_genuine_typed_lineage_required_before_probe_generation(
    damage, packets, lineages, preparation_arguments, no_execution,
):
    original = lineages["fol"]
    if damage == "foreign_lineage":
        class Foreign:
            lineage_json = original.lineage_json
            claims = original.claims
        changed = Foreign()
    elif damage == "mutable_claims":
        changed = replace(original, claims=list(original.claims))
    elif damage == "cross_family":
        changed = replace(original, claims=(lineages["tdfol"].claims[0], *original.claims[1:]))
    else:
        metadata = original.claims[0].metadata.to_dict()
        metadata["proof_authority"] = 0
        claim = replace(original.claims[0], metadata=FrozenMap(metadata))
        assert claim.to_dict() == original.claims[0].to_dict()
        assert claim.digest != original.claims[0].digest
        changed = replace(original, claims=(claim, *original.claims[1:]))
    with pytest.raises((ValueError, TypeError)):
        prepare(changed, packets["fol"], preparation_arguments["fol"])


def test_counterfeit_claim_getter_is_never_called(
    packets, lineages, preparation_arguments, no_execution,
):
    original = lineages["fol"]
    accessed = []
    def poison(self):
        accessed.append("claim_id")
        raise AssertionError("counterfeit claim descriptor executed")
    counterfeit_type = type("IRClaim", (), {"__module__": IRClaim.__module__, "claim_id": property(poison)})
    changed = replace(original, claims=(counterfeit_type(), *original.claims[1:]))
    with pytest.raises(ValueError):
        prepare(changed, packets["fol"], preparation_arguments["fol"])
    assert accessed == []


@pytest.mark.parametrize("damage", ("source", "review", "dependency"))
def test_original_source_review_and_dependency_arguments_are_replayed(
    damage, packets, lineages, preparation_arguments, no_execution,
):
    reviews = deepcopy(preparation_arguments["fol"]["review_inputs"])
    if damage == "source":
        reviews["component_raw"] += b" changed original source"
    elif damage == "review":
        reviews["policy"]["mode"] = "changed-review-mode"
    else:
        name = next(iter(reviews["observed_artifact_sha256s"]))
        reviews["observed_artifact_sha256s"][name] = None
    with pytest.raises(ValueError):
        prepare(lineages["fol"], packets["fol"], preparation_arguments["fol"], review_inputs=reviews)


def test_late_mutation_after_real_lineage_validation_refuses(
    packets, lineages, preparation_arguments, monkeypatch, no_execution,
):
    reviews = deepcopy(preparation_arguments["fol"]["review_inputs"])
    genuine = lineage_owner.validate_definition_use_preservation_theorem_lineage_v2
    completed = []
    def mutate_after_actual_validation(*args, **kwargs):
        result = genuine(*args, **kwargs)
        completed.append(result)
        reviews["injected_after_lineage_validation"] = "outside genuine replay"
        return result
    monkeypatch.setattr(lineage_owner, "validate_definition_use_preservation_theorem_lineage_v2",
                        mutate_after_actual_validation)
    with pytest.raises(ValueError):
        prepare(lineages["fol"], packets["fol"], preparation_arguments["fol"], review_inputs=reviews)
    assert len(completed) == 1


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_every_original_source_and_complete_project_population_is_bound(family, packets, preparations):
    preparation = preparations[family]
    document = manifest(preparation)
    files = dict(preparation.files)
    original_files = {path.removeprefix("project/"): raw
                      for path, raw in packets[family].files
                      if path.startswith("project/") and path != "project/corpus-manifest.json"}
    assert type(preparation.files) is tuple and len(preparation.files) == len(files) == 17
    assert tuple(files) == tuple(sorted(files))
    assert all(type(path) is str and type(text) is str for path, text in preparation.files)
    assert document["schema"] == "legal-corpus-v2-definition-use-preservation-elaboration-preparation/v1"
    assert len(original_files) == 16
    assert document["original_source_file_sha256"] == {path: sha(raw) for path, raw in original_files.items()}
    assert document["file_sha256"] == {path: sha(text.encode("utf-8")) for path, text in files.items()}
    assert set(files) - set(original_files) == {"LegalCorpusV2Elaboration.lean"}
    for path, raw in original_files.items():
        if path != "lakefile.toml":
            assert files[path].encode("utf-8") == raw
    assert len(document["expected_modules"]) == len(set(document["expected_modules"])) == 13
    assert set(document["module_imports"]) == set(document["expected_modules"])
    assert "LegalCorpusV2Elaboration" in document["expected_modules"]


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_probe_headers_and_namespace_bind_exact_original_declarations(family, lineages, preparations):
    document = manifest(preparations[family])
    entries = lineages[family].to_dict()["entries"]
    probes = document["probe_bindings"]
    source = dict(preparations[family].files)["LegalCorpusV2Elaboration.lean"]
    assert len(probes) == 15
    assert document["original_theorems"] == [entry["theorem_name"] for entry in entries]
    assert document["probe_theorems"] == [row["probe_theorem_name"] for row in probes]
    assert len(document["theorems"]) == len(set(document["theorems"])) == 30
    assert set(document["theorems"]) == set(document["original_theorems"] + document["probe_theorems"])
    assert set(document["original_theorems"]).isdisjoint(document["probe_theorems"])
    for entry, row in zip(entries, probes, strict=True):
        original = entry["theorem_name"]
        original_short = original.rsplit(".", 1)[1]
        probe = row["probe_theorem_name"]
        probe_short = probe.rsplit(".", 1)[1]
        assert row["original_theorem_name"] == original
        assert probe.rsplit(".", 1)[0] == entry["source_namespace"]
        assert row["original_header"] == entry["declaration_header"]
        prefix = "theorem " + original_short
        assert row["original_header"].startswith(prefix + " ")
        assert row["probe_header"] == "theorem " + probe_short + row["original_header"][len(prefix):]
        block = row["probe_block"]
        assert source.count(block) == 1
        assert "namespace " + entry["source_namespace"] + "\n" in block
        assert "end " + entry["source_namespace"] + "\n" in block
        assert row["probe_header"] + " := by\n" in block
        assert "#print axioms " + probe_short + "\n" in block
        command = row["check_command"]
        assert source.count(command) == 1
        assert "run_elab" in command
        assert original in command and probe in command


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_probe_applications_preserve_all_parameters_and_premise_identities(family, lineages, preparations):
    entries = lineages[family].to_dict()["entries"]
    probes = manifest(preparations[family])["probe_bindings"]
    occurrences = 0
    for claim, entry, row in zip(lineages[family].claims, entries, probes, strict=True):
        parameters = [name for binder in entry["parameter_binders"] for name in binder["names"]]
        premises = [premise["binder_name"] for premise in entry["proposition_premises"]]
        expected_arguments = parameters + premises
        assert row["argument_names"] == expected_arguments
        assert row["claim_digest"] == claim.digest == entry["claim_digest"]
        assert row["obligation_digest"] == claim.obligations[0].digest == entry["obligation_digest"]
        assert row["assumption_ids"] == list(claim.obligations[0].assumption_ids) == entry["assumption_ids"]
        application = "@" + entry["theorem_name"]
        if expected_arguments:
            application += " " + " ".join(expected_arguments)
        assert "exact " + application + "\n" in row["probe_block"]
        occurrences += len(premises)
    assert occurrences == 5


def test_pure_preparation_keeps_every_authority_and_mask_false(preparations, lineages):
    for family, preparation in preparations.items():
        document = manifest(preparation)
        assert all(document[key] is False for key in lineage_owner.FALSE_FLAGS)
        assert all(value is False for value in document["authority"].values())
        assert type(document["training_mask"]) is int and document["training_mask"] == 0
        assert type(document["evaluation_gold_mask"]) is int and document["evaluation_gold_mask"] == 0
        original = lineages[family].to_dict()
        assert document["original_preparation_state"] == original["original_preparation_state"]
        assert document["expected_binary_sha256"] == original["expected_binary_sha256"]


@pytest.mark.parametrize("damage", ("header", "premises", "namespace", "missing_probe", "proof_authority"))
def test_resealed_preparation_mutants_cannot_replace_regeneration(
    damage, packets, lineages, preparation_arguments, preparations, no_execution,
):
    original = preparations["fol"]
    document = manifest(original)
    row = document["probe_bindings"][0]
    if damage == "header":
        row["probe_header"] = row["probe_header"].replace("↔", "→")
    elif damage == "premises":
        row["argument_names"].pop()
        row["assumption_ids"].pop()
    elif damage == "namespace":
        row["probe_theorem_name"] = "ForeignNamespace." + row["probe_theorem_name"].rsplit(".", 1)[1]
    elif damage == "missing_probe":
        document["probe_bindings"].pop()
    else:
        document["proof_checked"] = True
        document["authority"]["proof"] = True
    changed = reseal(original, document)
    assert manifest(changed) == seal(manifest(changed))
    with pytest.raises(ValueError):
        validate(changed, lineages["fol"], packets["fol"], preparation_arguments["fol"])


def test_resealed_probe_source_change_refuses_even_with_updated_file_hash(
    packets, lineages, preparation_arguments, preparations, no_execution,
):
    original = preparations["fol"]
    files = dict(original.files)
    files["LegalCorpusV2Elaboration.lean"] += "\n-- caller changed the native target\n"
    document = manifest(original)
    document["file_sha256"]["LegalCorpusV2Elaboration.lean"] = sha(files["LegalCorpusV2Elaboration.lean"].encode())
    changed = reseal(original, document, tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        validate(changed, lineages["fol"], packets["fol"], preparation_arguments["fol"])


def test_preparation_storage_is_frozen_and_manifest_decoding_detached(preparations):
    preparation = preparations["fol"]
    raw = preparation.manifest_json
    detached = manifest(preparation)
    detached["training_mask"] = 1
    assert preparation.manifest_json == raw
    assert manifest(preparation)["training_mask"] == 0
    with pytest.raises((AttributeError, TypeError)):
        preparation.manifest_json = "{}"


def test_counterfeit_preparation_refuses_before_property_access(
    packets, lineages, preparation_arguments, preparations, no_execution,
):
    accessed = []
    def poison(self):
        accessed.append("manifest_json")
        raise AssertionError("counterfeit preparation descriptor executed")
    counterfeit_type = type("ElaborationPreparation", (), {
        "__module__": owner.__name__, "manifest_json": property(poison),
    })
    packet = packets["fol"]
    with pytest.raises(ValueError):
        owner.validate_definition_use_preservation_elaboration_v2(
            counterfeit_type(), lineages["fol"], packet.files,
            packet.data["corpus_preparation"], packet.data["assessment_raw"],
            expected_elaboration_preparation_sha256=preparation_pin(preparations["fol"]),
            **preparation_arguments["fol"],
        )
    assert accessed == []


def synthetic_type_records(preparation):
    """Fabricate inert parser data, never the actual types of these claims.

    All declarations below deliberately reuse a small well-formed Expr shape.
    A parser acceptance result is local data validation, not kernel execution.
    """
    expression = {"kind": "const", "name": {"kind": "str", "parent": {"kind": "anonymous"}, "value": "True"},
                  "levels": []}
    return [{
        "schema": "legal-corpus-v2-native-theorem-type-check/v1",
        "original_name": row["original_theorem_name"], "alias_name": row["probe_theorem_name"],
        "original_type": deepcopy(expression), "alias_type": deepcopy(expression),
        "original_level_params": [], "alias_level_params": [],
        "expr_equal": True, "kernel_defeq": True,
        "original_kernel_check": True, "alias_kernel_check": True,
        "closed_types": True, "prop_type": True, "level_params_equal": True,
    } for row in manifest(preparation)["probe_bindings"]]


def capture(records):
    return "".join("CORPUS_TYPE_CHECK:" + canonical(record).decode("utf-8") + "\n"
                   for record in records)


def test_synthetic_capture_local_parser_shape_does_not_execute(preparations, no_execution):
    for family in ("fol", "tdfol"):
        document = manifest(preparations[family])
        records = synthetic_type_records(preparations[family])
        observed, errors, passed = elaboration_native._type_observations(capture(records), "", document)
        assert passed is True and errors == []
        assert set(observed) == set(document["original_theorems"])
        axiom_capture = "".join("'" + name + "' does not depend on any axioms\n" for name in document["theorems"])
        dependencies, errors, passed = elaboration_native._axiom_observations(axiom_capture, "", document)
        assert passed is True and errors == []
        assert dependencies == {name: [] for name in document["theorems"]}


@pytest.mark.parametrize("damage", (
    "empty", "duplicate", "missing", "bad_flag", "cross_family", "unknown_key", "type_mismatch", "unknown_expr",
))
def test_synthetic_machine_capture_is_fail_closed(damage, preparations, no_execution):
    document = manifest(preparations["fol"])
    records = synthetic_type_records(preparations["fol"])
    if damage == "empty":
        records = []
    elif damage == "duplicate":
        records.append(deepcopy(records[0]))
    elif damage == "missing":
        records.pop()
    elif damage == "bad_flag":
        records[0]["expr_equal"] = 1
    elif damage == "cross_family":
        records[0] = synthetic_type_records(preparations["tdfol"])[0]
    elif damage == "unknown_key":
        records[0]["untrusted_authority"] = True
    elif damage == "type_mismatch":
        records[0]["alias_type"]["name"]["value"] = "False"
    else:
        records[0]["original_type"] = records[0]["alias_type"] = {"kind": "unknown"}
    _, errors, passed = elaboration_native._type_observations(capture(records), "", document)
    assert passed is False and errors


def test_synthetic_hidden_axiom_cannot_be_hidden_by_complete_empty_reports(preparations, no_execution):
    document = manifest(preparations["fol"])
    stdout = "".join("'" + name + "' does not depend on any axioms\n" for name in document["theorems"])
    stdout += "'" + document["theorems"][0] + "' depends on axioms: [sorryAx]\n"
    _, errors, passed = elaboration_native._axiom_observations(stdout, "", document)
    assert passed is False and errors


def test_deep_closed_type_capture_is_separate_from_compact_sealed_receipt(preparations, no_execution):
    """Deep valid capture grammar must fit its owner without widening shared limits.

    The fabricated proposition is nested And under unused Type quantifiers.
    This remains synthetic parser data; no native acceptance is asserted.
    """
    def name(parts):
        result = {"kind": "anonymous"}
        for part in parts:
            result = {"kind": "str", "parent": result, "value": part}
        return result
    def constant(label):
        return {"kind": "const", "name": name((label,)), "levels": []}
    expression = constant("True")
    for _ in range(22):
        expression = {"kind": "app", "fn": {"kind": "app", "fn": constant("And"),
                                             "arg": constant("True")}, "arg": expression}
    for index in range(8):
        expression = {
            "kind": "forallE", "binder_name": name((*("BinderNamespace" for _ in range(22)), "x" + str(index))),
            "binder_info": "default", "binder_type": {"kind": "sort", "level": {"kind": "succ", "of": {"kind": "zero"}}},
            "body": expression,
        }
    records = synthetic_type_records(preparations["fol"])
    for row in records:
        row["original_type"] = deepcopy(expression)
        row["alias_type"] = deepcopy(expression)
    observed, errors, passed = elaboration_native._type_observations(
        capture(records), "", manifest(preparations["fol"]),
    )
    assert passed is True and errors == [] and len(observed) == 15
    with pytest.raises(contracts.CorpusContractError, match="depth"):
        contracts.seal_record({"schema": "synthetic-deep-type-capture/v1",
                               "native_observations": {"type_checks": observed}})
    full_raw, compact = elaboration_native._type_capture_payload(observed)
    assert type(full_raw) is bytes and 0 < len(full_raw) <= elaboration_native.MAX_RECORD_BYTES
    assert full_raw == canonical(observed)
    assert json.loads(full_raw) == observed
    assert set(compact) == set(observed)
    checked_flags = ("expr_equal", "kernel_defeq", "original_kernel_check", "alias_kernel_check",
                     "closed_types", "prop_type", "level_params_equal")
    payload_fields = ("original_type", "alias_type", "original_level_params", "alias_level_params")
    for theorem, summary in compact.items():
        original = observed[theorem]
        assert summary["schema"] == "legal-corpus-v2-native-theorem-type-check-reference/v1"
        assert summary["original_name"] == theorem == original["original_name"]
        assert summary["alias_name"] == original["alias_name"]
        assert summary["record_sha256"] == sha(canonical(original))
        assert summary["record_bytes"] == len(canonical(original))
        assert all(summary[field] is True for field in checked_flags)
        for field in payload_fields:
            assert field not in summary
            assert summary[field + "_sha256"] == sha(canonical(original[field]))
            assert summary[field + "_bytes"] == len(canonical(original[field]))
    descriptor = {"path": "type-checks.json", "sha256": sha(full_raw), "bytes": len(full_raw)}
    sealed = contracts.seal_record({
        "schema": "synthetic-compact-type-capture/v1",
        "native_observations": {"type_checks": compact, "type_checks_file": descriptor,
                                "type_checks_sha256": sha(full_raw), "type_checks_bytes": len(full_raw)},
    })
    assert contracts.validate_record(sealed, schema="synthetic-compact-type-capture/v1",
                                     fields=("native_observations",)) == sealed
    assert sealed["native_observations"]["type_checks_file"] == descriptor



def _planned_physical_probe_inputs():
    """Authored source/diagnostic data for the pure preparation and readback APIs."""
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, QueryKind

    theorem = "PhysicalFixture.useDefinition"
    proposition = "∀ {Actor : Type}, True → True"
    toolchain = "leanprover/lean4:v4.34.1"
    source_path = "PhysicalFixture.lean"
    files = (
        (source_path, "import Lean\nnamespace PhysicalFixture\n"
         "theorem useDefinition : " + proposition + " := by intros; trivial\n"
         "example : " + proposition + " := @useDefinition\n"
         "#print axioms useDefinition\nend PhysicalFixture\n"),
        ("lakefile.toml", 'name = "fixture"\n[[lean_lib]]\nname = "legal"\nroots = ["PhysicalFixture"]\n'),
        ("lean-toolchain", toolchain + "\n"),
    )
    context = {
        "theorem": theorem, "source_namespace": "PhysicalFixture", "source_path": source_path,
        "proposition_utf8_sha256": sha(proposition.encode()),
        "theorem_binding": {
            "kind": "whole_norm_definition_expansion",
            "premise_kind": "independently_denoted_source_definition",
            "desired_equivalence_hypothesis": False,
        },
    }
    payload = {
        "schema": "legal-corpus-v4-planned-physical-whole-norm-request/v2",
        "resource_profile": "physical-whole-project-output/v1",
        "encoding": "lean4-physical-project-proposition-source/v1",
        "context": context, "context_sha256": sha(canonical(context)), "proposition_source": proposition,
        "project": {
            "target": "legal", "toolchain": toolchain, "expected_modules": ["PhysicalFixture"],
            "module_imports": {"PhysicalFixture": []},
            "files": [{"path": path, "bytes": len(body.encode()), "sha256": sha(body.encode())}
                      for path, body in files],
        },
        "authority": owner.AUTHORITY,
        "premise_remains_quantified": True, "elaborated_type_verified": False,
        "dispatch_qualified": False, "execution_profile_qualified": False,
    }
    request = BackendRequest(
        request_id="authored-physical-probe", claim_id="authored-physical-claim", claim_digest="1" * 64,
        obligation_id="authored-physical-obligation", obligation_digest="2" * 64, assumption_ids=(),
        logic_family="lean4", declaration_id=theorem, query_kind=QueryKind.THEOREM_PROOF,
        bounds=ExecutionBounds(max_output_bytes=8 * 1024**2),
        requested_backend_id="legal-corpus-v4-physical-project-kernel@1", payload=payload,
    )
    return request, files


def test_planned_physical_type_probe_preserves_original_proposition_and_sources():
    request, files = _planned_physical_probe_inputs()
    prepared = owner.prepare_planned_physical_whole_norm_type_probe_v2(
        request, files, expected_request_sha256=request.digest)
    state = prepared.to_dict()
    project = dict(prepared.files)
    original = dict(files)
    probe = project["PhysicalWholeNormElaboration.lean"].splitlines()
    assert set(project) == {*original, "PhysicalWholeNormElaboration.lean"}
    assert all(project[path] == original[path] for path in original if path != "lakefile.toml")
    assert 'roots = ["PhysicalFixture","PhysicalWholeNormElaboration"]' in project["lakefile.toml"]
    alias = "PhysicalFixture.physical_whole_norm_type_" + request.digest
    assert state["original_theorem"] == request.declaration_id and state["alias_theorem"] == alias
    assert state["request_sha256"] == request.digest and state["obligation_digest"] == request.obligation_digest
    assert probe[state["alias_axiom_report_line"] - 1] == "#print axioms " + alias.rsplit(".", 1)[1]
    assert probe[state["type_report_line"] - 1].endswith("`" + request.declaration_id + " `" + alias)
    assert any(" : ∀ {Actor : Type}, True → True := @_root_.PhysicalFixture.useDefinition" in row for row in probe)
    assert state["file_sha256"] == {path: sha(body.encode()) for path, body in project.items()}
    assert state["preparation_only"] and not state["elaborated_type_verified"]
    assert all(value is False for value in state["authority"].values())


@pytest.mark.parametrize("mutation", ["request-digest", "original-source", "repinned-missing-ABI"])
def test_planned_physical_type_probe_refuses_changed_original_binding(mutation):
    request, files = _planned_physical_probe_inputs()
    expected = request.digest
    if mutation == "request-digest":
        expected = "0" * 64
    elif mutation == "original-source":
        files = ((files[0][0], files[0][1] + "\n"), *files[1:])
    else:
        source, body = files[0]
        files = ((source, body.replace("example :", "#check")), *files[1:])
        payload = request.to_dict()["payload"]
        payload["project"]["files"][0] = {"path": source, "bytes": len(files[0][1].encode()),
                                           "sha256": sha(files[0][1].encode())}
        request = replace(request, payload=payload)
        expected = request.digest
    with pytest.raises(ValueError, match="independently pinned|original namespace ABI"):
        owner.prepare_planned_physical_whole_norm_type_probe_v2(
            request, files, expected_request_sha256=expected)


@pytest.mark.parametrize("mutation", [None, "wrong-line", "wrong-original-line",
    "wrong-original-column", "duplicate", "no-original-axioms",
    "stderr-marker", "defeq-false", "loose-variable", "wrong-digest", "expr-equal-contradiction"])
def test_planned_physical_type_capture_binds_exact_kernel_diagnostics(mutation):
    request, files = _planned_physical_probe_inputs()
    prepared = owner.prepare_planned_physical_whole_norm_type_probe_v2(
        request, files, expected_request_sha256=request.digest)
    state = prepared.to_dict()
    original, alias = state["original_theorem"], state["alias_theorem"]
    original_type = {
        "kind": "forallE", "binder_name": {"kind": "str", "parent": {"kind": "anonymous"}, "value": "p"},
        "binder_info": "default", "binder_type": {"kind": "sort", "level": {"kind": "zero"}},
        "body": {"kind": "bvar", "index": 0},
    }
    row = {
        "schema": owner.PHYSICAL_TYPE_OBSERVATION_SCHEMA, "original_name": original, "alias_name": alias,
        "original_type": original_type, "alias_type": {**original_type, "binder_name": {"kind": "anonymous"}},
        "original_level_params": [], "alias_level_params": [], "expr_equal": False,
        "kernel_defeq": True, "original_kernel_check": True, "alias_kernel_check": True,
        "closed_types": True, "prop_type": True, "level_params_equal": True,
    }
    module = state["probe_module"] + ".lean"
    if mutation == "expr-equal-contradiction":
        row["expr_equal"] = True
    if mutation == "defeq-false":
        row["kernel_defeq"] = False
    if mutation == "loose-variable":
        row["alias_type"]["body"] = {"kind": "bvar", "index": 1}
    line = state["type_report_line"] + (1 if mutation == "wrong-line" else 0)
    marker = f"info: {module}:{line}:0: CORPUS_TYPE_CHECK:".encode() + canonical(row) + b"\n"
    original_line = 6 if mutation == "wrong-original-line" else 5
    original_column = 1 if mutation == "wrong-original-column" else 0
    original_report = (f"info: {state['source_path']}:{original_line}:{original_column}: "
                       f"'{original}' does not depend on any axioms\n").encode()
    alias_report = f"info: {module}:{state['alias_axiom_report_line']}:0: '{alias}' does not depend on any axioms\n".encode()
    stdout = (b"" if mutation == "no-original-axioms" else original_report) + alias_report + marker
    if mutation == "duplicate":
        stdout += marker
    stderr = marker if mutation == "stderr-marker" else b""
    options = dict(expected_preparation_sha256=owner.preparation_sha256(prepared),
                   expected_stdout_sha256="0" * 64 if mutation == "wrong-digest" else sha(stdout),
                   expected_stderr_sha256=sha(stderr))
    if mutation is None:
        retained = elaboration_native.read_planned_physical_whole_norm_type_capture_v2(
            prepared, stdout, stderr, **options)
        assert retained == canonical({original: row})
    else:
        with pytest.raises(ValueError):
            elaboration_native.read_planned_physical_whole_norm_type_capture_v2(
                prepared, stdout, stderr, **options)


def _checked_release_type_capture_fixture(label, *, checked_changes=None, review_changes=None):
    """Small fictional retained claims; real seals/typed validators, no execution."""
    from ipfs_datasets_py.logic.autoformal import corpus_qualification as qualification
    from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

    def digest(role):
        return sha(("fictional " + label + " " + role).encode())

    def record_cid(role):
        return seal({"schema": "authored-type-capture-fixture-leaf/v1",
                     "label": label, "role": role})["record_cid"]

    request, files = _planned_physical_probe_inputs()
    context = request.to_dict()["payload"]["context"]
    units = {}
    for role, unit_id in (("unit", "norm-" + label), ("source_definition", "definition-" + label)):
        units[role] = {
            "unit_id": unit_id, "complete_ir_sha256": digest(role + " ir"),
            "interpretation_record_cid": record_cid(role + " interpretation"),
            "scope_record_cid": record_cid(role + " scope"),
            "source_occurrence_cid": record_cid(role + " occurrence"),
            "source_use_binding_sha256": digest(role + " use"),
            "source_version_cid": record_cid("source version"),
        }
    units["unit"]["relational_request_sha256"] = digest("relational request")
    component_raw = {role: canonical({"fictional": label, "role": role})
                     for role in ("graph", "admission", "preservation", "reviewed_crosswalk", "dependency")}
    context.update({"physical_request_sha256": digest("physical request"),
                    **{role + "_sha256": sha(component_raw[role])
                       for role in ("graph", "admission", "preservation")},
                    "realization_sha256": digest("realization"), **units})
    # The original V4 report commits decoded preparation separately from raw transport.
    context["preservation_sha256"] = digest("decoded preservation preparation")
    payload = request.to_dict()["payload"]
    payload.update(context=context, context_sha256=sha(canonical(context)))
    request = replace(request, request_id="authored-checked-type-" + label, payload=payload,
                      claim_digest=digest("claim"), obligation_digest=digest("obligation"))
    prepared = owner.prepare_planned_physical_whole_norm_type_probe_v2(
        request, files, expected_request_sha256=request.digest)
    state = prepared.to_dict()
    original_type = {"kind": "forallE", "binder_name": {"kind": "str",
        "parent": {"kind": "anonymous"}, "value": "p"}, "binder_info": "default",
        "binder_type": {"kind": "sort", "level": {"kind": "zero"}}, "body": {"kind": "bvar", "index": 0}}
    row = {
        "schema": owner.PHYSICAL_TYPE_OBSERVATION_SCHEMA,
        "original_name": state["original_theorem"], "alias_name": state["alias_theorem"],
        "original_type": original_type,
        "alias_type": {**original_type, "binder_name": {"kind": "anonymous"}},
        "original_level_params": [], "alias_level_params": [], "expr_equal": False,
        "kernel_defeq": True, "original_kernel_check": True, "alias_kernel_check": True,
        "closed_types": True, "prop_type": True, "level_params_equal": True,
    }
    module = state["probe_module"] + ".lean"
    stdout = (f"info: {state['source_path']}:5:0: '{state['original_theorem']}' does not depend on any axioms\n"
              f"info: {module}:{state['alias_axiom_report_line']}:0: '{state['alias_theorem']}' does not depend on any axioms\n"
              f"info: {module}:{state['type_report_line']}:0: CORPUS_TYPE_CHECK:").encode() + canonical(row) + b"\n"
    review = seal({
        "schema": "legal-corpus-physical-v4-current-review-observation/v1",
        "request_sha256": context["physical_request_sha256"], "graph_sha256": context["graph_sha256"],
        "admission_sha256": context["admission_sha256"], "registry_sha256": digest("registry"),
        "policy_sha256": digest("policy"), "reviews_sha256": digest("reviews"),
        "at_time_utc": "2026-11-26T00:00:00Z", "caller_observation_sha256": digest("caller observation"),
        "current_assessment_sha256": digest("assessment"), "dependency_invalidation_sha256": digest("invalidation"),
        "evaluation_clock_authenticated": False, "registry_freshness_authenticated": False,
        **({} if review_changes is None else review_changes),
    })
    checked = seal({
        "schema": "legal-corpus-physical-v4-checked-native-observation/v1",
        **{key: context[key] for key in ("physical_request_sha256", "graph_sha256", "admission_sha256",
            "preservation_sha256", "realization_sha256", "unit", "source_definition", "proposition_utf8_sha256")},
        "planned_request_sha256": request.digest, "current_review_observation_cid": review["record_cid"],
        "live_result_cid": record_cid("retained conditional native result"),
        "declaration": request.declaration_id, "claim_digest": request.claim_digest,
        "obligation_digest": request.obligation_digest,
        "retained_receipt_sha256": digest("original receipt"), "retained_packet_sha256": digest("original packet inventory"),
        "native_execution_authenticated": True, "checked_under_explicit_hypotheses": True,
        "premise_remains_quantified": True, "axiom_dependencies": [],
        "qualified_request_execution": False, "proof_receipt_issued": False,
        **({} if checked_changes is None else checked_changes),
    })
    report = {
        "schema": "legal-uscode-release-closure-report/v4", "reviewed_version": 4,
        "profile": "reviewed-source-use-whole-norm-physical-source-replay/v1",
        "instance_identity_profile": "reviewed-source-use/v1",
        "definition_application_profile": "whole-norm-definition-expansion/v1",
        "local_replay_complete": True, "local_source_cache_entity_bindings_verified": True,
        "independent_reviewed_crosswalk_verified": True,
        **dict.fromkeys(("admission_mask", "release_mask", "training_mask", "gold_mask", "evaluation_gold_mask"), 0),
        **dict.fromkeys(("admitted", "release_ready", "release_eligible", "formalized", "proof_verified",
                        "source_semantics_verified", "model_or_compiler_execution_performed"), False),
        "request_sha256": context["physical_request_sha256"],
        **{role + "_sha256": sha(component_raw[role])
           for role in ("graph", "admission", "preservation", "reviewed_crosswalk")},
        "artifacts": [{"artifact_id": "fictional:" + label + ":" + role, "family": role,
                       "bytes": len(raw), "sha256": sha(raw)} for role, raw in component_raw.items()],
        "fixture_only": True, "current_review_observation": review, "checked_native_observation": checked,
        "unit_ids": [checked["unit"]["unit_id"], checked["source_definition"]["unit_id"]],
        "unit_preservation_bindings": [{**checked[key], "kind": kind}
                                       for key, kind in (("unit", "norm"), ("source_definition", "definition"))],
    }
    report["preservation_sha256"] = context["preservation_sha256"]
    components = {role: cid_for_bytes(raw) for role, raw in component_raw.items()}
    evidence = seal({
        "schema": "legal-corpus-physical-v4-qualification-evidence/v1",
        **{key: report[key] for key in ("reviewed_version", "instance_identity_profile", "definition_application_profile",
            "profile", "request_sha256", "graph_sha256", "admission_sha256", "preservation_sha256",
            "reviewed_crosswalk_sha256", "fixture_only")},
        "artifact_cid": components["graph"], "component_cids": components,
        "ordered_unit_ids": report["unit_ids"], "permitted_uses": ["fictional_test_only"],
        "formal_assumptions": [], "preservation_obligations": [request.obligation_id],
        "retained_native": None,
        "current_review_observation": review, "checked_native_observation": checked,
    })
    dimensions = {name: {"status": status, "evidence_cids": refs} for name, status, refs in (
        ("processing", "complete", [evidence["record_cid"]]),
        ("source_integrity", "verified", [components["reviewed_crosswalk"]]),
        ("interpretation", "reviewed", [components["admission"], review["record_cid"]]),
        ("representation", "supported_complete", [components["preservation"]]),
        ("dependency", "resolved", [components["dependency"]]),
    )}
    declared = qualification.prepare_qualification(artifact_cid=components["graph"], profile=report["profile"],
                                                   theorem_requested=True, dimensions=dimensions)
    report.update(declared_eligibility_evidence=evidence, declared_qualification=declared,
                  declared_eligibility=qualification.derive_eligibility(
                      declared, artifact_cid=components["graph"], profile=report["profile"]))
    raw = canonical(report)
    return {"request": request, "files": files, "prepared": prepared, "row": row, "stdout": stdout,
            "stderr": b"", "report": report, "options": {
                "checked_release_report_raw": raw, "expected_checked_release_report_sha256": sha(raw),
                "expected_retained_receipt_sha256": digest("original receipt"),
                "expected_retained_packet_sha256": digest("original packet inventory"),
                "expected_preparation_sha256": owner.preparation_sha256(prepared),
                "expected_stdout_sha256": sha(stdout), "expected_stderr_sha256": sha(b""),
            }}


@pytest.mark.parametrize("release_id", ["one", "two"])
def test_checked_release_type_capture_preserves_exact_retained_provenance(release_id):
    case = _checked_release_type_capture_fixture(release_id)
    report_before = canonical(case["report"])
    observed = elaboration_native.read_checked_release_physical_whole_norm_type_capture_v2(
        case["request"], case["files"], case["stdout"], case["stderr"], **case["options"])
    original = elaboration_native.read_planned_physical_whole_norm_type_capture_v2(
        case["prepared"], case["stdout"], case["stderr"], **{key: case["options"][key] for key in (
            "expected_preparation_sha256", "expected_stdout_sha256", "expected_stderr_sha256")})
    assert set(observed) == {"type_capture", "provenance"}
    assert observed["type_capture"] == original == canonical({case["request"].declaration_id: case["row"]})
    provenance = observed["provenance"]
    assert seal(provenance) == provenance
    checked = case["report"]["checked_native_observation"]
    for key in ("physical_request_sha256", "graph_sha256", "admission_sha256", "preservation_sha256",
                "realization_sha256", "unit", "source_definition", "proposition_utf8_sha256", "declaration",
                "planned_request_sha256", "claim_digest", "obligation_digest",
                "retained_receipt_sha256", "retained_packet_sha256"):
        assert provenance[key] == checked[key]
    assert provenance["checked_native_observation_cid"] == checked["record_cid"]
    assert provenance["current_review_observation_cid"] == checked["current_review_observation_cid"]
    assert provenance["retained_live_result_cid"] == checked["live_result_cid"]
    assert provenance["release_qualification_evidence_cid"] == case["report"]["declared_eligibility_evidence"]["record_cid"]
    assert provenance["declared_qualification_cid"] == case["report"]["declared_qualification"]["record_cid"]
    assert provenance["declared_eligibility_cid"] == case["report"]["declared_eligibility"]["record_cid"]
    assert provenance["checked_release_report_sha256"] == sha(report_before)
    assert provenance["type_capture_sha256"] == sha(original)
    assert provenance["planned_context_sha256"] == case["request"].to_dict()["payload"]["context_sha256"]
    for key, option in (("probe_preparation_sha256", "expected_preparation_sha256"),
                        ("probe_stdout_sha256", "expected_stdout_sha256"), ("probe_stderr_sha256", "expected_stderr_sha256")):
        assert provenance[key] == case["options"][option]
    assert provenance["fixture_only"] is True and provenance["premise_remains_quantified"] is True
    preserved_transport = next(row for row in case["report"]["artifacts"] if row["family"] == "preservation")
    assert preserved_transport["sha256"] != provenance["preservation_sha256"]
    assert provenance["checked_under_explicit_hypotheses"] is True and provenance["axiom_dependencies"] == []
    assert provenance["fresh_native_execution_performed"] is False and provenance["proof_receipt_issued"] is False
    assert provenance["authority"] == owner.AUTHORITY and all(value is False for value in provenance["authority"].values())
    assert type(provenance["training_mask"]) is int and provenance["training_mask"] == 0
    assert type(provenance["evaluation_gold_mask"]) is int and provenance["evaluation_gold_mask"] == 0
    assert canonical(case["report"]) == report_before
    assert case["report"]["declared_eligibility"]["views"]["checked_lean"]["declared_eligible"] is False
    assert case["report"]["declared_qualification"]["dimensions"]["proof"]["status"] == "pending"


@pytest.mark.parametrize("damage", ["foreign-report", "foreign-plan", "coherent-receipt", "coherent-packet",
    "coherent-unit", "coherent-review-link", "nested-seal", "report-pin", "preparation-pin", "stdout-pin",
    "repinned-alias", "repinned-open-type", "authority-mask", "duplicate-component", "changed-component-transport"])
def test_checked_release_type_capture_refuses_cross_release_and_repinned_mutations(damage):
    case = _checked_release_type_capture_fixture("one")
    request, files, stdout, stderr = (case[key] for key in ("request", "files", "stdout", "stderr"))
    options = dict(case["options"])
    if damage == "foreign-report":
        other = _checked_release_type_capture_fixture("two")
        options.update({key: other["options"][key] for key in (
            "checked_release_report_raw", "expected_checked_release_report_sha256",
            "expected_retained_receipt_sha256", "expected_retained_packet_sha256")})
    elif damage == "foreign-plan":
        other = _checked_release_type_capture_fixture("two")
        request, files = other["request"], other["files"]
    elif damage.startswith("coherent-"):
        if damage in ("coherent-receipt", "coherent-packet"):
            field = "retained_receipt_sha256" if damage == "coherent-receipt" else "retained_packet_sha256"
            changes = {field: sha(("different exact " + field).encode())}
        elif damage == "coherent-unit":
            changes = {"unit": _checked_release_type_capture_fixture("two")["report"]["checked_native_observation"]["unit"]}
        else:
            changes = {"current_review_observation_cid": case["report"]["declared_qualification"]["record_cid"]}
        changed = _checked_release_type_capture_fixture("one", checked_changes=changes)
        options.update({key: changed["options"][key] for key in (
            "checked_release_report_raw", "expected_checked_release_report_sha256")})
    elif damage in ("nested-seal", "authority-mask", "duplicate-component", "changed-component-transport"):
        report = deepcopy(case["report"])
        if damage == "nested-seal":
            report["checked_native_observation"]["claim_digest"] = "f" * 64
        elif damage == "authority-mask":
            report["admission_mask"] = 1
        elif damage == "duplicate-component":
            report["artifacts"].append(deepcopy(report["artifacts"][0]))
        else:
            next(row for row in report["artifacts"] if row["family"] == "preservation")["sha256"] = "f" * 64
        options.update(checked_release_report_raw=canonical(report),
                       expected_checked_release_report_sha256=sha(canonical(report)))
    elif damage.endswith("-pin"):
        field = {"report-pin": "expected_checked_release_report_sha256",
                 "preparation-pin": "expected_preparation_sha256", "stdout-pin": "expected_stdout_sha256"}[damage]
        options[field] = "0" * 64
    else:
        row = deepcopy(case["row"])
        if damage == "repinned-alias":
            row["alias_name"] += "Foreign"
        else:
            row["alias_type"]["body"]["index"] = 1
        assert stdout.count(canonical(case["row"])) == 1
        stdout = stdout.replace(canonical(case["row"]), canonical(row))
        options["expected_stdout_sha256"] = sha(stdout)
    with pytest.raises(ValueError):
        elaboration_native.read_checked_release_physical_whole_norm_type_capture_v2(
            request, files, stdout, stderr, **options)


@pytest.mark.parametrize("field,value,error", [
    pytest.param("registry_sha256", "invalid", "registry_sha256", id="registry-pin"),
    pytest.param("policy_sha256", "A" * 64, "policy_sha256", id="policy-pin"),
    pytest.param("reviews_sha256", True, "reviews_sha256", id="reviews-pin"),
    pytest.param("caller_observation_sha256", None, "caller_observation_sha256", id="caller-observation-pin"),
    pytest.param("current_assessment_sha256", "1" * 63, "current_assessment_sha256", id="assessment-pin"),
    pytest.param("dependency_invalidation_sha256", "g" * 64, "dependency_invalidation_sha256", id="invalidation-pin"),
    pytest.param("at_time_utc", "2026-11-26T00:00:00+00:00", "explicit UTC seconds", id="utc-format"),
    pytest.param("at_time_utc", "2026-02-30T00:00:00Z", "valid UTC calendar", id="utc-calendar"),
])
def test_checked_release_type_capture_refuses_malformed_current_review_observation(field, value, error):
    valid = _checked_release_type_capture_fixture("one")
    changed = _checked_release_type_capture_fixture("one", review_changes={field: value})
    report = changed["report"]
    review = report["current_review_observation"]
    assert review[field] == value
    assert report["checked_native_observation"]["current_review_observation_cid"] == review["record_cid"]
    assert report["declared_eligibility_evidence"]["current_review_observation"] == review
    assert changed["request"] == valid["request"] and changed["files"] == valid["files"]
    assert changed["stdout"] == valid["stdout"] and changed["stderr"] == valid["stderr"]
    assert changed["options"]["expected_checked_release_report_sha256"] != valid["options"]["expected_checked_release_report_sha256"]
    with pytest.raises(ValueError, match=error):
        elaboration_native.read_checked_release_physical_whole_norm_type_capture_v2(
            changed["request"], changed["files"], changed["stdout"], changed["stderr"], **changed["options"])
