"""Candidate kernel-type projection from portable synthetic retained packets.

Every historical tool observation, PID and compiled artifact below is synthetic.
The genuine source/review, packet, lineage and elaboration owners replay their
inputs. No fixture establishes execution authenticity, kernel acceptance, legal
meaning or training authority. All runtime work belongs in the owned runner.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_v2 as preparer
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_native_v2 as native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_packet_v2 as reader
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_kernel_claims_v2 as owner
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_native_v2 as original_native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_theorem_lineage_v2 as lineage_owner
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.common import duckdb_proof_store
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, IRClaim
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ProofReceipt


_SPEC = importlib.util.spec_from_file_location(
    "_genuine_kernel_claim_old_packet_fixtures",
    Path(__file__).with_name("test_legal_corpus_definition_use_preservation_packet_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_OLD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _OLD
_SPEC.loader.exec_module(_OLD)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def seal(value):
    return contracts.seal_record({key: item for key, item in value.items()
                                  if key not in {"record_cid", "cid_scope"}})


def lean_name(text):
    result = {"kind": "anonymous"}
    for part in text.split("."):
        result = {"kind": "str", "parent": result, "value": part}
    return result


def name_text(value):
    if value["kind"] == "anonymous":
        return ""
    parent = name_text(value["parent"])
    return (parent + "." if parent else "") + str(value["value"])


def const(name, levels=()):
    return {"kind": "const", "name": lean_name(name), "levels": list(levels)}


def app(function, *arguments):
    for argument in arguments:
        function = {"kind": "app", "fn": function, "arg": argument}
    return function


def bound(context, name):
    return {"kind": "bvar", "index": len(context) - 1 - context.index(name)}


def formula(target, context):
    return app(const(target), *(bound(context, name) for name in ("Entity", "Agent", "i", "t")))


def closed_type(entry):
    """Independent closed-recipe encoding; never parse or execute Lean source.

    Build each binder type in its preceding context so hAlias correctly shifts
    its de Bruijn references after hDonor. The full forall telescope stays intact.
    """
    module, suffix = entry["theorem_name"].rsplit(".", 1)
    zero = {"kind": "zero"}
    one = {"kind": "succ", "of": zero}
    if suffix == "native_value_exact":
        return app(const("Eq", (one,)), const("LegalCorpusV2.NativeValue"),
                   app(const("LegalCorpusV2.toNativeValue"), const(module + ".typedNativeAst")),
                   const(module + ".actualNativeValue"))
    if suffix == "native_ast_closed":
        return app(const("Eq", (one,)), const("Bool"),
                   app(const("LegalCorpusV2.closed"), app(const("List.nil", (zero,)), const("String")),
                       const(module + ".typedNativeAst")), const("Bool.true"))
    context, binders = [], []
    for parameter in entry["parameter_binders"]:
        for name in parameter["names"]:
            if name in ("Entity", "Agent"):
                binder_type, info = {"kind": "sort", "level": one}, "implicit"
            elif name == "i":
                binder_type, info = app(const("LegalCorpusV2.Interpretation"),
                                        bound(context, "Entity"), bound(context, "Agent")), "default"
            elif name == "t":
                binder_type, info = const("Nat"), "default"
            else:
                assert name == "entity"
                binder_type, info = bound(context, "Entity"), "default"
            binders.append((name, info, binder_type))
            context.append(name)
    for premise in entry["proposition_premises"]:
        binders.append((premise["binder_name"], "default", formula(premise["qualified_target"], context)))
        context.append(premise["binder_name"])
    if suffix == "consumer_predicate_iff_donor_body":
        donor = entry["proposition_premises"][0]["qualified_target"].rsplit(".", 1)[0]
        arguments = [bound(context, name) for name in ("Entity", "Agent", "i", "entity", "t")]
        body = app(const("Iff"), app(const(module + ".consumerPredicateAt"), *arguments),
                   app(const(donor + ".bodyAt"), *arguments))
    elif suffix == "joint_of_components":
        body = formula(module + ".formula_0", context)
    elif suffix == "joint_matches_original":
        body = app(const("Iff"), formula(module + ".jointAt", context), formula(module + ".formula_0", context))
    else:
        assert suffix == "denotation_matches_native"
        denotation = app(const("LegalCorpusV2.denote"), bound(context, "Entity"), bound(context, "Agent"),
                         bound(context, "i"), const(module + ".typedNativeAst"),
                         app(const("LegalCorpusV2.emptyEnvironment"), bound(context, "Entity")), bound(context, "t"))
        body = app(const("Iff"), denotation, formula(entry["target_declaration"], context))
    for name, info, binder_type in reversed(binders):
        body = {"kind": "forallE", "binder_name": lean_name(name), "binder_info": info,
                "binder_type": binder_type, "body": body}
    return body


def captures(lineage, preparation):
    entries = lineage.to_dict()["entries"]
    probes = preparation.to_dict()["probe_bindings"]
    result = {}
    for entry, probe in zip(entries, probes, strict=True):
        expression = closed_type(entry)
        result[entry["theorem_name"]] = {
            "schema": native.TYPE_CHECK_SCHEMA, "original_name": entry["theorem_name"],
            "alias_name": probe["probe_theorem_name"], "original_type": expression,
            "alias_type": deepcopy(expression), "original_level_params": [], "alias_level_params": [],
            "expr_equal": True, "kernel_defeq": True, "original_kernel_check": True,
            "alias_kernel_check": True, "closed_types": True, "prop_type": True, "level_params_equal": True,
        }
    return result


@dataclass(frozen=True)
class SyntheticElaborationPacket:
    original: object
    lineage: object
    preparation: object
    original_arguments: dict
    files: tuple


def synthetic_elaboration_packet(family):
    original = _OLD.synthetic_packet(family)
    old_arguments = _OLD.arguments(original) | {
        "expected_packet_observation_sha256": sha(_OLD.read(original).observation_json.encode()),
    }
    lineage = lineage_owner.prepare_definition_use_preservation_theorem_lineage_v2(
        original.files, original.data["corpus_preparation"], original.data["assessment_raw"], **old_arguments)
    preparation = preparer.prepare_definition_use_preservation_elaboration_v2(
        lineage, original.files, original.data["corpus_preparation"], original.data["assessment_raw"],
        expected_lineage_sha256=lineage_owner.lineage_sha256(lineage), **old_arguments)
    manifest = preparation.to_dict()
    types = captures(lineage, preparation)
    type_raw, compact = native._type_capture_payload(types)
    source_files = {name: text.encode() for name, text in preparation.files}
    artifact_files = {
        ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean":
        b"synthetic elaboration artifact; no execution or proof: " + module.encode()
        for module in manifest["expected_modules"]
    }
    stdout = "".join("'" + name + "' does not depend on any axioms\n" for name in manifest["theorems"])
    stdout += "".join("CORPUS_TYPE_CHECK:" + canonical(types[name]).decode() + "\n"
                      for name in manifest["original_theorems"])
    logs = {"stdout.txt": stdout.encode(), "stderr.txt": b"", "runner-error.txt": b""}
    observed = deepcopy(json.loads(dict(original.files)["build-receipt.json"])["native_observations"])
    for key in ("installed_toolchain_verified", "conditional_theorems", "preservation_theorems",
                "concrete_kernel_status", "conditional_kernel_status"):
        observed.pop(key)
    observed.update({
        "expected_modules": manifest["expected_modules"], "compiled_modules": manifest["expected_modules"],
        "executed_project_sha256": {name: sha(raw) for name, raw in source_files.items()},
        "producer_pins": native._producer_pins(manifest, native._owners()),
        "installed_pair_binary_verified": True, "installed_stdlib_artifact_closure_verified": False,
        "artifact_sha256": {name: sha(raw) for name, raw in artifact_files.items()},
        "artifact_bytes": {name: len(raw) for name, raw in artifact_files.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifact_files},
        "theorems": manifest["theorems"], "original_theorems": manifest["original_theorems"],
        "probe_theorems": manifest["probe_theorems"],
        "theorem_axiom_dependencies": {name: [] for name in manifest["theorems"]},
        "type_checks": compact, "type_checks_passed": True, "type_check_errors": [],
        "type_checks_sha256": sha(type_raw), "type_checks_bytes": len(type_raw),
        "type_checks_file": {"path": "type-checks.json", "sha256": sha(type_raw), "bytes": len(type_raw)},
        "type_check_scope": "actual original and namespace-preserving alias theorem types; no inferred legal interpretation",
        "termination_reason": "completed",
        "stdout": stdout.encode()[:native.MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace"),
        "log_sha256": {name: sha(raw) for name, raw in logs.items()},
        "log_bytes": {name: len(raw) for name, raw in logs.items()},
        "receipt_text_truncated": len(logs["stdout.txt"]) > native.MAX_LOG_PREVIEW_BYTES,
    })
    observed_flags = {
        "backend_executed": True, "native_execution_performed": True, "fresh_native_execution_performed": True,
        "installed_compiler_revalidated": True, "lean_compilation_verified": True, "proof_checked": True,
        "kernel_proofs_checked": True, "elaborated_type_verified": True, "elaborated_type_equality_verified": True,
        "kernel_definitional_equality_verified": True, "kernel_probe_aliases_checked": True,
    }
    receipt = seal({
        "schema": native.BUILD_SCHEMA, "profile": native.PROFILE, "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": preparer.preparation_sha256(preparation),
        "preparation_manifest_sha256": sha(preparation.manifest_json.encode()),
        "lineage_sha256": lineage_owner.lineage_sha256(lineage),
        "packet_observation_sha256": old_arguments["expected_packet_observation_sha256"],
        "packet_bundle_sha256": old_arguments["expected_bundle_sha256"],
        "receipt_file_sha256": old_arguments["expected_receipt_file_sha256"],
        "corpus_preparation_full_canonical_sha256": old_arguments["expected_corpus_preparation_sha256"],
        "assessment_file_sha256": old_arguments["expected_assessment_file_sha256"],
        "toolchain": old_arguments["toolchain"], "original_preparation_state": manifest["original_preparation_state"],
        "native_observations": observed, "build_passed": True,
        "status": "corpus_theorem_type_elaboration_checks_passed",
        "proof_scope": "Fifteen actual original theorem types exactly match namespace-preserving generated alias types, with kernel checks and empty axiom inventories for thirty original/alias declarations. The original donor, consumer and alias hypotheses remain parameters; no fact or legal/source correspondence is established.",
        "trust_boundary": [
            "The installed standard library and dynamically loaded compiler libraries are external trust premises; only the installed sibling lake/lean ELF pair is pinned and version-probed.",
            "This clean build consumes seventeen regenerated source inputs and no retained compiled artifact.",
            "Native observations do not construct a FormalizationArtifact, BackendRequest, BackendAttempt, ProofResult or typed ProofReceipt and do not authorize legal/cache admission.",
        ],
        "authority": dict(native.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **(native.FALSE_FLAGS | observed_flags),
    })
    packet = {"project/" + name: raw for name, raw in source_files.items()}
    packet["project/corpus-manifest.json"] = preparation.manifest_json.encode()
    packet.update({"executed-inputs/" + name: raw for name, raw in source_files.items()})
    packet.update({"compiled/" + path.removeprefix(".lake/build/lib/lean/"): raw for path, raw in artifact_files.items()})
    packet.update(logs)
    packet["type-checks.json"] = type_raw
    packet["build-receipt.json"] = canonical(receipt)
    assert len(packet) == 53
    return SyntheticElaborationPacket(original, lineage, preparation, old_arguments, tuple(sorted(packet.items())))


def reader_arguments(base, files=None):
    files = base.files if files is None else files
    mapping = dict(files)
    return base.original_arguments | {
        "expected_native_receipt_file_sha256": sha(mapping["build-receipt.json"]),
        "expected_type_payload_file_sha256": sha(mapping["type-checks.json"]),
        "expected_native_bundle_sha256": reader.packet_sha256(files),
        "expected_elaboration_preparation_sha256": preparer.preparation_sha256(base.preparation),
        "expected_lineage_sha256": lineage_owner.lineage_sha256(base.lineage),
    }


def synthetic_kernel_inputs(family):
    """Portable helper for owned tests: (old_packet, lineage, files53, readerargs)."""
    base = synthetic_elaboration_packet(family)
    return base.original, base.lineage, base.files, reader_arguments(base)


def read(base, arguments, *, files=None, **overrides):
    return reader.validate_definition_use_preservation_elaboration_packet_v2(
        base.files if files is None else files, base.lineage, base.original.files,
        base.original.data["corpus_preparation"], base.original.data["assessment_raw"], **(arguments | overrides))


def prepare(base, arguments, *, files=None, lineage=None, **overrides):
    return owner.prepare_definition_use_preservation_kernel_claims_v2(
        base.files if files is None else files, base.lineage if lineage is None else lineage, base.original.files,
        base.original.data["corpus_preparation"], base.original.data["assessment_raw"], **(arguments | overrides))


def validate(projection, base, arguments, **overrides):
    return owner.validate_definition_use_preservation_kernel_claims_v2(
        projection, base.files, base.lineage, base.original.files,
        base.original.data["corpus_preparation"], base.original.data["assessment_raw"],
        **(arguments | {"expected_projection_sha256": sha(projection.projection_json.encode())} | overrides))


@pytest.fixture(scope="module")
def packets():
    return {family: synthetic_elaboration_packet(family) for family in ("fol", "tdfol")}


@pytest.fixture(scope="module")
def packet_arguments(packets):
    return {family: reader_arguments(base) for family, base in packets.items()}


@pytest.fixture(scope="module")
def retained(packets, packet_arguments):
    return {family: read(base, packet_arguments[family]) for family, base in packets.items()}


@pytest.fixture(scope="module")
def projection_arguments(packet_arguments, retained):
    return {family: arguments | {"expected_elaboration_observation_sha256": sha(retained[family].observation_json.encode())}
            for family, arguments in packet_arguments.items()}


@pytest.fixture(scope="module")
def projections(packets, projection_arguments):
    return {family: prepare(base, projection_arguments[family]) for family, base in packets.items()}


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("kernel candidate projection reached native execution, process probing, backend request, proof issuance or cache")
    monkeypatch.setattr(original_native, "build_definition_use_preservation_native_v2", forbidden)
    monkeypatch.setattr(original_native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(original_native, "_binary_recheck", forbidden)
    monkeypatch.setattr(native, "build_definition_use_preservation_elaboration_native_v2", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(process, "_linux_owned_identity", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(BackendRequest, "for_claim", forbidden)
    monkeypatch.setattr(ProofReceipt, "issue", forbidden)
    monkeypatch.setattr(duckdb_proof_store.DuckDBProofStore, "put", forbidden)
    class Deny:
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == name or fullname.startswith(name + ".")
                   for name in ("duckdb", "torch", "transformers")):
                forbidden()
    deny = Deny()
    sys.meta_path.insert(0, deny)
    yield
    sys.meta_path.remove(deny)


def projection_document(projection):
    return json.loads(projection.projection_json)


def resealed_projection(projection, document, claims=None):
    return replace(projection, projection_json=canonical(seal(document)).decode(),
                   claims=projection.claims if claims is None else claims)


def test_both_public_imports_are_stdlib_only():
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','multiformats','pyarrow','duckdb','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_kernel_candidate_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in sys.argv[2:]: assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    for module, public in (
        (reader, ("RetainedElaborationPacket", "packet_sha256", "observation_sha256",
                  "validate_definition_use_preservation_elaboration_packet_v2")),
        (owner, ("KernelClaimProjection", "projection_sha256",
                 "prepare_definition_use_preservation_kernel_claims_v2",
                 "validate_definition_use_preservation_kernel_claims_v2")),
    ):
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, module.__file__, *public],
                                capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_complete_retained_elaboration_readback_is_pure_and_non_authorizing(
    family, packets, packet_arguments, retained, no_execution,
):
    result = read(packets[family], packet_arguments[family])
    document = result.to_dict()
    assert result == retained[family] and len(result.files) == 53
    assert document["native_bundle_sha256"] == packet_arguments[family]["expected_native_bundle_sha256"]
    assert document["type_payload_file_sha256"] == packet_arguments[family]["expected_type_payload_file_sha256"]
    assert len(document["type_check_references"]) == 15
    assert all(document[field] is False for field in reader.FALSE_FLAGS)
    assert all(value is False for value in document["authority"].values())
    assert type(document["training_mask"]) is int and document["training_mask"] == 0
    assert type(document["evaluation_gold_mask"]) is int and document["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_genuine_candidate_projection_is_deterministic_without_execution(
    family, packets, projection_arguments, projections, no_execution,
):
    original = projections[family]
    assert type(original) is owner.KernelClaimProjection
    assert type(original.claims) is tuple and len(original.claims) == 15
    assert all(type(claim) is IRClaim and len(claim.obligations) == 1 for claim in original.claims)
    assert owner.projection_sha256(original) == sha(original.projection_json.encode())
    assert prepare(packets[family], projection_arguments[family]) == original
    assert validate(original, packets[family], projection_arguments[family]) == original


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_new_claim_statement_is_exact_complete_closed_kernel_type(family, packets, projections):
    full = json.loads(dict(packets[family].files)["type-checks.json"])
    rows = projection_document(projections[family])["entries"]
    for claim, row in zip(projections[family].claims, rows, strict=True):
        observation = full[claim.declaration_id]
        expected = {"schema": "lean-kernel-proposition/v1", "type": observation["original_type"],
                    "level_parameters": observation["original_level_params"]}
        assert claim.statement == claim.obligations[0].statement == canonical(expected).decode()
        assert row["kernel_statement_json"] == claim.statement
        assert row["kernel_statement_sha256"] == sha(claim.statement.encode())
        assert row["kernel_type_sha256"] == sha(canonical(expected["type"]))
        assert row["level_parameters_sha256"] == sha(canonical(expected["level_parameters"]))
        assert claim.metadata["statement_kind"] == "lean_kernel_proposition_json"
        assert claim.metadata["closed_quantified_target"] is True
        assert claim.metadata["proof_authority"] is False


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_full_telescope_retains_universal_parameters_and_bound_hypotheses(family, packets, projections):
    document = projection_document(projections[family])
    originals = packets[family].lineage.to_dict()["entries"]
    assert document["outer_binder_count"] == 34
    assert document["universal_parameter_count"] == 29
    assert document["proposition_premise_association_count"] == 5
    assert document["external_assumption_count"] == 0
    total = hypotheses = 0
    for old, row, claim in zip(originals, document["entries"], projections[family].claims, strict=True):
        expression = json.loads(claim.statement)["type"]
        names, infos, captured_binders = [], [], []
        while expression["kind"] == "forallE":
            names.append(name_text(expression["binder_name"]))
            infos.append(expression["binder_info"])
            captured_binders.append({"binder_name": expression["binder_name"], "binder_info": expression["binder_info"],
                                     "binder_type": expression["binder_type"]})
            expression = expression["body"]
        parameters = [name for binder in old["parameter_binders"] for name in binder["names"]]
        premises = [premise["binder_name"] for premise in old["proposition_premises"]]
        assert names == parameters + premises
        assert infos == [("implicit" if name in ("Entity", "Agent") else "default") for name in names]
        assert len(row["outer_binders"]) == len(names)
        assert len(row["proposition_premise_associations"]) == len(premises)
        for index, binding in enumerate(row["outer_binders"]):
            expected_context = {"schema": "lean-kernel-telescope-prefix/v1", "context_depth": index,
                                "binders": captured_binders[:index],
                                "de_bruijn_domains_are_relative_to_preceding_binders": True}
            assert binding["binder_index"] == binding["context_depth"] == index
            assert binding["binder_path"] == ["body"] * index
            assert binding["binder_name"] == names[index] and binding["binder_info"] == infos[index]
            assert binding["binder_type_json"] == canonical(captured_binders[index]["binder_type"]).decode()
            assert binding["binder_type_sha256"] == sha(binding["binder_type_json"].encode())
            assert binding["prefix_context_json"] == canonical(expected_context).decode()
            assert binding["prefix_context_sha256"] == sha(binding["prefix_context_json"].encode())
            assert binding["domain_is_standalone_closed_proposition"] is False
            assert binding["binder_kind"] == ("quantified_proposition_hypothesis" if names[index] in premises else "universal_parameter")
        for source, association in zip(old["proposition_premises"], row["proposition_premise_associations"], strict=True):
            assert association["source_assumption_id"] == source["assumption_id"]
            assert association["source_qualified_target"] == source["qualified_target"]
            assert association["source_range"] == source["range"]
            assert association["hypothesis_established_as_fact"] is False
            assert association["external_assumption_created"] is False
        assert claim.assumptions == () and claim.obligations[0].assumption_ids == ()
        assert row["external_assumption_ids"] == []
        total += len(names)
        hypotheses += len(premises)
    assert (total, hypotheses) == (34, 5)


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_old_header_claims_are_unchanged_and_new_identities_remain_distinct(family, packets, projections):
    base = packets[family]
    old_raw = base.lineage.lineage_json
    old_digests = [claim.digest for claim in base.lineage.claims]
    rows = projection_document(projections[family])["entries"]
    for old, new, row in zip(base.lineage.claims, projections[family].claims, rows, strict=True):
        assert old.claim_id != new.claim_id and old.digest != new.digest
        assert old.obligations[0].obligation_id != new.obligations[0].obligation_id
        assert old.obligations[0].digest != new.obligations[0].digest
        assert old.declaration_id == new.declaration_id == row["theorem_name"]
        assert new.domain == lineage_owner.DOMAIN
        assert row["source_header_claim"] == {
            "claim_id": old.claim_id, "claim_digest": old.digest, "declaration_id": old.declaration_id,
            "declaration_header": old.statement, "obligation_id": old.obligations[0].obligation_id,
            "obligation_digest": old.obligations[0].digest, "assumption_ids": list(old.obligations[0].assumption_ids),
        }
        assert "source_header_claim" not in new.metadata and "evidence_refs" not in new.metadata
    assert base.lineage.lineage_json == old_raw
    assert [claim.digest for claim in base.lineage.claims] == old_digests
    assert {claim.digest for claim in projections["fol"].claims}.isdisjoint(claim.digest for claim in projections["tdfol"].claims)


def test_transient_historical_run_changes_do_not_change_kernel_claim_identity(
    packets, projections, no_execution,
):
    base = packets["fol"]
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    observed = receipt["native_observations"]
    observed["elapsed_seconds"] = 0.125
    life = observed["native_lifecycle"]
    life["parent"]["pid"] += 1_000_000
    life["leader"]["pid"] += 1_000_000
    life["leader"]["parent_pid"] = life["parent"]["pid"]
    life["leader"]["process_group_id"] = life["leader"]["session_id"] = life["leader"]["pid"]
    observed["pid"] = life["leader"]["pid"]
    files["stdout.txt"] += b"synthetic alternate-run telemetry\n"
    observed["stdout"] = files["stdout.txt"][:native.MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace")
    observed["log_sha256"]["stdout.txt"], observed["log_bytes"]["stdout.txt"] = sha(files["stdout.txt"]), len(files["stdout.txt"])
    observed["receipt_text_truncated"] = len(files["stdout.txt"]) > native.MAX_LOG_PREVIEW_BYTES
    files["build-receipt.json"] = canonical(seal(receipt))
    changed = replace(base, files=tuple(sorted(files.items())))
    arguments = reader_arguments(changed)
    observation = read(changed, arguments)
    projected = prepare(changed, arguments | {"expected_elaboration_observation_sha256": sha(observation.observation_json.encode())})
    assert projected.projection_json != projections["fol"].projection_json
    assert projected.claims == projections["fol"].claims


@pytest.mark.parametrize("field", (
    "expected_native_receipt_file_sha256", "expected_type_payload_file_sha256", "expected_native_bundle_sha256",
    "expected_elaboration_preparation_sha256", "expected_lineage_sha256",
))
def test_independent_retained_native_pins_are_mandatory(field, packets, packet_arguments, no_execution):
    with pytest.raises(ValueError):
        read(packets["fol"], packet_arguments["fol"], **{field: "0" * 64})


def test_wrong_elaboration_observation_pin_cannot_prepare_claims(packets, projection_arguments, no_execution):
    with pytest.raises(ValueError):
        prepare(packets["fol"], projection_arguments["fol"], expected_elaboration_observation_sha256="0" * 64)


def test_wrong_independent_projection_pin_refuses(packets, projection_arguments, projections, no_execution):
    with pytest.raises(ValueError):
        validate(projections["fol"], packets["fol"], projection_arguments["fol"], expected_projection_sha256="0" * 64)


def test_resealed_historical_producer_pin_must_match_current_qualified_owner(packets, no_execution):
    base = packets["fol"]
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    pins = receipt["native_observations"]["producer_pins"]
    pins[next(iter(pins))] = "0" * 64
    files["build-receipt.json"] = canonical(seal(receipt))
    changed = replace(base, files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        read(changed, reader_arguments(changed))


@pytest.mark.parametrize("group", ("compiled", "type_payload", "log"))
def test_changed_archived_bytes_refuse_after_bundle_repin(group, packets, packet_arguments, no_execution):
    base = packets["fol"]
    files = dict(base.files)
    if group == "compiled":
        path = next(name for name in files if name.startswith("compiled/"))
    else:
        path = "type-checks.json" if group == "type_payload" else "stdout.txt"
    files[path] += b" changed archived bytes"
    changed = tuple(sorted(files.items()))
    with pytest.raises(ValueError):
        read(base, packet_arguments["fol"], files=changed,
             expected_native_bundle_sha256=reader.packet_sha256(changed))


@pytest.mark.parametrize("damage", ("open_type", "unknown_expr", "hidden_axiom"))
def test_resealed_synthetic_native_capture_cannot_bypass_reader_grammar(
    damage, packets, no_execution,
):
    base = packets["fol"]
    files = dict(base.files)
    types = json.loads(files["type-checks.json"])
    first = next(iter(types))
    if damage != "hidden_axiom":
        expression = {"kind": "bvar", "index": 0} if damage == "open_type" else {"kind": "unknown"}
        types[first]["original_type"] = types[first]["alias_type"] = expression
    type_raw = canonical(types)
    receipt = json.loads(files["build-receipt.json"])
    observed = receipt["native_observations"]
    # Deliberately reseal all address commitments without calling the native
    # compactor, which correctly refuses malformed captures itself. This makes
    # the public retained reader confront an internally addressed forgery.
    for name, record in types.items():
        compact = observed["type_checks"][name]
        compact["record_sha256"], compact["record_bytes"] = sha(canonical(record)), len(canonical(record))
        for field in ("original_type", "alias_type", "original_level_params", "alias_level_params"):
            compact[field + "_sha256"] = sha(canonical(record[field]))
            compact[field + "_bytes"] = len(canonical(record[field]))
    manifest = base.preparation.to_dict()
    stdout = "".join("'" + name + "' does not depend on any axioms\n" for name in manifest["theorems"])
    stdout += "".join("CORPUS_TYPE_CHECK:" + canonical(types[name]).decode() + "\n"
                      for name in manifest["original_theorems"])
    if damage == "hidden_axiom":
        stdout += "'" + first + "' depends on axioms: [sorryAx]\n"
    files["type-checks.json"], files["stdout.txt"] = type_raw, stdout.encode()
    observed["type_checks_sha256"], observed["type_checks_bytes"] = sha(type_raw), len(type_raw)
    observed["type_checks_file"] = {"path": "type-checks.json", "sha256": sha(type_raw), "bytes": len(type_raw)}
    observed["stdout"] = files["stdout.txt"][:native.MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace")
    observed["log_sha256"]["stdout.txt"], observed["log_bytes"]["stdout.txt"] = sha(files["stdout.txt"]), len(files["stdout.txt"])
    observed["receipt_text_truncated"] = len(files["stdout.txt"]) > native.MAX_LOG_PREVIEW_BYTES
    files["build-receipt.json"] = canonical(seal(receipt))
    changed = replace(base, files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        read(changed, reader_arguments(changed))


@pytest.mark.parametrize("damage", ("statement", "namespace", "binder", "premise", "domain", "proof_authority"))
def test_self_resealed_projection_cannot_substitute_typed_or_kernel_bindings(
    damage, packets, projection_arguments, projections, no_execution,
):
    original = projections["fol"]
    document = projection_document(original)
    row = document["entries"][0]
    claims = original.claims
    if damage == "statement":
        row["kernel_statement_json"] = canonical({"schema": "lean-kernel-proposition/v1",
                                                 "type": const("True"), "level_parameters": []}).decode()
    elif damage == "namespace":
        row["source_namespace"] = "ForeignNamespace"
    elif damage == "binder":
        row["outer_binders"].pop()
    elif damage == "premise":
        row["proposition_premise_associations"].pop()
    elif damage == "domain":
        changed = replace(claims[0], domain="legal")
        claims = (changed, *claims[1:])
        document["claims"][0] = changed.to_dict()
        row["claim_digest"] = changed.digest
    else:
        document["authority"]["proof"] = True
    changed = resealed_projection(original, document, claims)
    with pytest.raises(ValueError):
        validate(changed, packets["fol"], projection_arguments["fol"])


def test_false_cannot_be_replaced_by_zero_in_typed_kernel_claim_metadata(
    packets, projection_arguments, projections, no_execution,
):
    original = projections["fol"]
    old_claim = original.claims[0]
    metadata = old_claim.metadata.to_dict()
    metadata["proof_authority"] = 0
    changed_claim = replace(old_claim, metadata=FrozenMap(metadata))
    assert changed_claim.to_dict() == old_claim.to_dict() and changed_claim.digest != old_claim.digest
    changed = replace(original, claims=(changed_claim, *original.claims[1:]))
    with pytest.raises(ValueError):
        validate(changed, packets["fol"], projection_arguments["fol"])


def test_counterfeit_claim_refuses_before_getter_access(packets, projection_arguments, projections, no_execution):
    original = projections["fol"]
    accessed = []
    def poison(self):
        accessed.append("claim_id")
        raise AssertionError("counterfeit claim getter executed")
    counterfeit = type("IRClaim", (), {"__module__": IRClaim.__module__, "claim_id": property(poison)})
    changed = replace(original, claims=(counterfeit(), *original.claims[1:]))
    with pytest.raises(ValueError):
        validate(changed, packets["fol"], projection_arguments["fol"])
    assert accessed == []


@pytest.mark.parametrize("field", ("training_mask", "evaluation_gold_mask"))
def test_zero_masks_require_ordinary_integers(field, packets, projection_arguments, projections, no_execution):
    original = projections["fol"]
    document = projection_document(original)
    document[field] = False
    changed = resealed_projection(original, document)
    with pytest.raises(ValueError):
        validate(changed, packets["fol"], projection_arguments["fol"])


def test_late_review_mutation_after_genuine_elaboration_reader_refuses(
    packets, projection_arguments, monkeypatch, no_execution,
):
    reviews = deepcopy(projection_arguments["fol"]["review_inputs"])
    genuine = reader.validate_definition_use_preservation_elaboration_packet_v2
    completed = []
    def mutate_after_actual_readback(*args, **kwargs):
        result = genuine(*args, **kwargs)
        completed.append(result)
        reviews["late_outside_genuine_replay"] = "changed"
        return result
    monkeypatch.setattr(reader, "validate_definition_use_preservation_elaboration_packet_v2", mutate_after_actual_readback)
    with pytest.raises(ValueError):
        prepare(packets["fol"], projection_arguments["fol"], review_inputs=reviews)
    assert len(completed) == 1


@pytest.mark.parametrize("damage", ("source", "review"))
def test_full_original_source_review_inputs_remain_mandatory(
    damage, packets, projection_arguments, no_execution,
):
    reviews = deepcopy(projection_arguments["fol"]["review_inputs"])
    if damage == "source":
        reviews["component_raw"] += b" changed original source"
    else:
        reviews["policy"]["mode"] = "changed-review-mode"
    with pytest.raises(ValueError):
        prepare(packets["fol"], projection_arguments["fol"], review_inputs=reviews)


def test_projection_storage_is_frozen_and_decoding_detached(projections):
    projection = projections["fol"]
    before = projection.projection_json
    detached = projection_document(projection)
    detached["training_mask"] = 1
    assert projection.projection_json == before and projection_document(projection)["training_mask"] == 0
    with pytest.raises((AttributeError, TypeError)):
        projection.projection_json = "{}"


