"""Exact declaration lineage from genuinely replayed, synthetic byte packets.

Historical compiler claims and artifacts below are deliberately synthetic.
Their independent unit pins establish byte identity, never compilation, proof
authentication, statutory correspondence, or the truth of a declared premise.
The existing public source/review preparation and retained reader run unmocked.
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
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_native_v2 as native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_packet_v2 as packet_owner
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_theorem_lineage_v2 as owner
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, IRClaim


_SPEC = importlib.util.spec_from_file_location(
    "_genuine_preservation_theorem_lineage_packet_fixtures",
    Path(__file__).with_name("test_legal_corpus_definition_use_preservation_packet_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _FIXTURE
_SPEC.loader.exec_module(_FIXTURE)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def seal(value):
    return contracts.seal_record({key: item for key, item in value.items()
                                  if key not in {"record_cid", "cid_scope"}})


@pytest.fixture(scope="module")
def packets():
    return {family: _FIXTURE.synthetic_packet(family) for family in ("fol", "tdfol")}


@pytest.fixture(scope="module")
def inputs(packets):
    return {
        family: _FIXTURE.arguments(packet) | {
            "expected_packet_observation_sha256": sha(_FIXTURE.read(packet).observation_json.encode()),
        }
        for family, packet in packets.items()
    }


@pytest.fixture(scope="module")
def lineages(packets, inputs):
    return {family: prepare(packet, inputs[family]) for family, packet in packets.items()}


@pytest.fixture
def base(packets):
    return packets["fol"]


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("declaration lineage reached a compiler, process probe, model, database or proof execution")
    monkeypatch.setattr(native, "build_definition_use_preservation_native_v2", forbidden)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native, "_binary_recheck", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(process, "_linux_owned_identity", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    class DenyBackendImport:
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == name or fullname.startswith(name + ".")
                   for name in ("duckdb", "torch", "transformers")):
                forbidden()
    deny = DenyBackendImport()
    sys.meta_path.insert(0, deny)
    yield
    sys.meta_path.remove(deny)


def prepare(base, arguments, **overrides):
    return owner.prepare_definition_use_preservation_theorem_lineage_v2(
        base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
        **(arguments | overrides),
    )


def validate(lineage, base, arguments, **overrides):
    return owner.validate_definition_use_preservation_theorem_lineage_v2(
        lineage, base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
        **(arguments | {"expected_lineage_sha256": owner.lineage_sha256(lineage)} | overrides),
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
spec=importlib.util.spec_from_file_location('_lineage_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('RetainedCorpusTheoremLineage','lineage_sha256',
             'prepare_definition_use_preservation_theorem_lineage_v2',
             'validate_definition_use_preservation_theorem_lineage_v2'):
    assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, owner.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_each_family_has_fifteen_genuine_typed_declarations(family, packets, inputs, lineages, no_execution):
    lineage = lineages[family]
    manifest = json.loads(dict(packets[family].files)["project/corpus-manifest.json"])
    assert type(lineage.claims) is tuple and len(lineage.claims) == 15
    assert all(type(claim) is IRClaim for claim in lineage.claims)
    assert [claim.metadata["theorem_name"] for claim in lineage.claims] == manifest["theorems"]
    assert [claim.declaration_id for claim in lineage.claims] == manifest["theorems"]
    assert len({claim.claim_id for claim in lineage.claims}) == 15
    assert len({claim.digest for claim in lineage.claims}) == 15
    assert all(len(claim.obligations) == 1 for claim in lineage.claims)
    assert all(claim.statement == claim.obligations[0].statement for claim in lineage.claims)
    assert prepare(packets[family], inputs[family]) == lineage
    assert validate(lineage, packets[family], inputs[family]) == lineage


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_only_two_theorems_have_five_explicit_proposition_premises(family, lineages):
    claims = lineages[family].claims
    by_suffix = {claim.metadata["theorem_name"].rsplit(".", 1)[1]: claim for claim in claims[:3]}
    alias = by_suffix["consumer_predicate_iff_donor_body"]
    joint = by_suffix["joint_of_components"]
    equivalent = by_suffix["joint_matches_original"]
    assert len(alias.assumptions) == 2
    assert len(joint.assumptions) == 3
    assert equivalent.assumptions == ()
    assert sum(len(claim.assumptions) for claim in claims) == 5
    for claim in claims:
        assert claim.obligations[0].assumption_ids == tuple(item.assumption_id for item in claim.assumptions)
    assert len({(claim.claim_id, item.assumption_id) for claim in claims for item in claim.assumptions}) == 5
    assert all(claim.assumptions == () for claim in claims[3:])


def test_family_and_role_identities_never_collapse(lineages):
    fol, tdfol = lineages["fol"], lineages["tdfol"]
    assert owner.lineage_sha256(fol) != owner.lineage_sha256(tdfol)
    assert {claim.digest for claim in fol.claims}.isdisjoint(claim.digest for claim in tdfol.claims)
    for lineage in (fol, tdfol):
        matches = [claim for claim in lineage.claims if claim.metadata["theorem_name"].endswith(".denotation_matches_native")]
        assert len(matches) == len({claim.statement for claim in matches}) == 4


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_every_exact_utf8_range_is_bound_to_the_unchanged_source(family, packets, lineages):
    packet = dict(packets[family].files)
    entries = lineages[family].to_dict()["entries"]
    unicode_offsets = []
    for entry, claim in zip(entries, lineages[family].claims, strict=True):
        ranges = entry["byte_ranges"]
        assert set(ranges) == {"header", "proof_marker", "proof_body", "axiom_command", "block"}
        for item in ranges.values():
            source = packet[item["path"]]
            raw = source[item["start_byte"]:item["end_byte"]]
            assert 0 <= item["start_byte"] < item["end_byte"] <= len(source)
            assert item["bytes"] == len(raw)
            assert item["sha256"] == sha(raw)
            assert item["raw_utf8"].encode("utf-8") == raw
        assert ranges["header"]["raw_utf8"] == entry["declaration_header"] == claim.statement
        assert ranges["header"]["raw_utf8"].startswith("theorem " + entry["theorem_name"].rsplit(".", 1)[1] + " ")
        assert ranges["proof_marker"]["raw_utf8"] == " := by\n"
        assert ranges["header"]["end_byte"] == ranges["proof_marker"]["start_byte"]
        assert ranges["proof_marker"]["end_byte"] == ranges["proof_body"]["start_byte"]
        assert ranges["proof_body"]["end_byte"] == ranges["axiom_command"]["start_byte"]
        assert ranges["axiom_command"]["raw_utf8"] == "#print axioms " + entry["theorem_name"].rsplit(".", 1)[1] + "\n"
        assert ranges["block"]["raw_utf8"] == "".join(ranges[key]["raw_utf8"] for key in
                                                      ("header", "proof_marker", "proof_body", "axiom_command"))
        source = packet[ranges["header"]["path"]]
        prefix = source[:ranges["header"]["start_byte"]]
        if len(prefix) != len(prefix.decode("utf-8")):
            unicode_offsets.append(entry["theorem_name"])
        assert entry["statement_kind"] == "lean_declaration_header"
        assert entry["logic_family"] == "lean4"
    # Actual AST string values before certificate declarations contain Unicode;
    # character offsets would therefore select different bytes.
    assert len(unicode_offsets) >= 12


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_lineage_readback_has_no_fresh_proof_or_legal_authority(family, packets, inputs, lineages):
    value = lineages[family].to_dict()
    manifest = json.loads(dict(packets[family].files)["project/corpus-manifest.json"])
    assert value["schema"] == "legal-corpus-v2-preservation-theorem-lineage/v1"
    assert value["profile"] == "retained-corpus-preservation-opaque-theorem-lineage/v1"
    assert value["theorem_count"] == 15 and value["proposition_premise_count"] == 5
    assert value["original_conditional_theorems"] == manifest["conditional_theorems"]
    assert value["preservation_theorems"] == manifest["preservation_theorems"]
    assert value["original_preparation_state"] == manifest["original_preparation_state"]
    assert value["packet_observation_sha256"] == inputs[family]["expected_packet_observation_sha256"]
    assert value["packet_bundle_sha256"] == inputs[family]["expected_bundle_sha256"]
    assert value["receipt_file_sha256"] == inputs[family]["expected_receipt_file_sha256"]
    assert value["native_families"] == dict.fromkeys(("donor", "consumer", "alias", "joint"), family)
    assert all(value[name] is False for name in packet_owner.FALSE_FLAGS)
    assert all(value[name] is False for name in (
        "elaborated_type_verified", "executable_kernel_target_prepared",
        "formalization_artifact_created", "backend_request_prepared",
        "typed_native_attempt_observed", "typed_theorem_result_observed",
        "theorem_receipt_issued", "compiled_artifact_execution_reused",
        "elaborated_term_dependencies_verified", "source_prose_correspondence_proved",
    ))
    assert all(item is False for item in value["authority"].values())
    assert value["training_mask"] == value["evaluation_gold_mask"] == 0
    assert value["future_native_handoff"]["status"] == "not_prepared"
    assert value["claims"] == [claim.to_dict() for claim in lineages[family].claims]
    for entry, claim in zip(value["entries"], lineages[family].claims, strict=True):
        assert entry["status"] == "candidate" and entry["proof_usable"] is False
        assert entry["native_family"] == family
        assert entry["historical_axiom_dependencies"] == []
        assert entry["claim_id"] == claim.claim_id and entry["claim_digest"] == claim.digest
        assert entry["declaration_id"] == claim.declaration_id
        assert entry["obligation_id"] == claim.obligations[0].obligation_id
        assert entry["obligation_digest"] == claim.obligations[0].digest
        assert entry["assumption_ids"] == [assumption.assumption_id for assumption in claim.assumptions]
    pins = value["producer_pins"]
    assert pins[str(Path(owner.__file__).resolve())] == sha(Path(owner.__file__).read_bytes())
    assert pins[str(Path(packet_owner.__file__).resolve())] == sha(Path(packet_owner.__file__).read_bytes())
    assert owner.lineage_sha256(lineages[family]) == sha(lineages[family].lineage_json.encode("utf-8"))


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_universal_parameters_are_distinct_from_assumed_propositions(family, packets, lineages):
    packet = dict(packets[family].files)
    manifest = json.loads(packet["project/corpus-manifest.json"])
    targets = {row["role"]: row["target_declaration"] for row in manifest["preservation_fragments"]}
    common = [
        (["Entity", "Agent"], "{Entity Agent : Type}", "universal_type_parameters"),
        (["i"], "(i : Interpretation Entity Agent)", "universal_interpretation_parameter"),
        (["t"], "(t : Nat)", "universal_time_parameter"),
    ]
    for entry, claim in zip(lineages[family].to_dict()["entries"], lineages[family].claims, strict=True):
        suffix = entry["theorem_name"].rsplit(".", 1)[1]
        expected = [] if suffix in {"native_value_exact", "native_ast_closed"} else list(common)
        names = []
        if suffix == "consumer_predicate_iff_donor_body":
            expected.append((["entity"], "(entity : Entity)", "universal_entity_parameter"))
            names = ["hDonor", "hAlias"]
        elif suffix == "joint_of_components":
            names = ["hDonor", "hConsumer", "hAlias"]
        assert [(row["names"], row["binder"], row["kind"]) for row in entry["parameter_binders"]] == expected
        assert [row["binder_name"] for row in entry["proposition_premises"]] == names
        for parameter in entry["parameter_binders"]:
            span = parameter["range"]
            assert span["raw_utf8"] == parameter["binder"]
            assert packet[span["path"]][span["start_byte"]:span["end_byte"]].decode() == parameter["binder"]
        for premise, assumption in zip(entry["proposition_premises"], claim.assumptions, strict=True):
            role = {"hDonor": "donor", "hConsumer": "consumer", "hAlias": "alias"}[premise["binder_name"]]
            assert premise["qualified_target"] == targets[role]
            assert premise["assumption_id"] == assumption.assumption_id
            assert premise["proposition"] == assumption.statement
            assert premise["range"]["raw_utf8"] == premise["binder"]
            assert assumption.metadata["truth_established"] is False
            assert assumption.metadata["engineering_hypothesis_only"] is True
            assert assumption.metadata["qualified_target"] == targets[role]
            assert assumption.source_refs == (entry["byte_ranges"]["header"]["path"],)
        if suffix == "consumer_predicate_iff_donor_body":
            assert entry["proposition_premises"][1]["proposition"] == "formula_0 i t"
        assert claim.metadata["opaque_source_identity_only"] is True
        assert claim.metadata["elaborated_type_verified"] is False
        assert claim.metadata["executable_kernel_target_prepared"] is False
        assert claim.metadata["proof_authority"] is False


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_complete_declared_import_closure_retains_actual_module_identities(family, packets, lineages):
    packet = dict(packets[family].files)
    manifest = json.loads(packet["project/corpus-manifest.json"])
    historical = json.loads(packet["build-receipt.json"])["native_observations"]
    fragments = {row["role"]: row for row in manifest["preservation_fragments"]}
    prelude_sha = sha(packet["project/LegalCorpusV2/Prelude.lean"])
    semantics_path = "project/" + manifest["semantics_module"].replace(".", "/") + ".lean"
    semantics_sha = sha(packet[semantics_path])
    assert prelude_sha != fragments["donor"]["prelude_sha256"]
    assert semantics_sha != manifest["semantics_sha256"]
    for entry in lineages[family].to_dict()["entries"]:
        expected_modules = set()
        def visit(module):
            if module in expected_modules:
                return
            expected_modules.add(module)
            for dependency in manifest["module_imports"][module]:
                visit(dependency)
        visit(entry["source_module"])
        closure = entry["declared_import_closure"]
        assert {row["module"] for row in closure} == expected_modules
        assert len(closure) == len(expected_modules)
        assert entry["dependency_scope"] == "declared_transitive_import_closure_not_elaborated_term_dependencies"
        for row in closure:
            relative = row["module"].replace(".", "/")
            assert row["direct_imports"] == manifest["module_imports"][row["module"]]
            for key, path in (
                ("source", "project/" + relative + ".lean"),
                ("executed_source", "executed-inputs/" + relative + ".lean"),
                ("compiled_artifact", "compiled/" + relative + ".olean"),
            ):
                assert row[key] == {"path": path, "bytes": len(packet[path]), "sha256": sha(packet[path])}
            assert row["source"]["sha256"] == row["executed_source"]["sha256"]
            assert row["compiled_artifact"]["sha256"] == historical["artifact_sha256"][
                ".lake/build/lib/lean/" + relative + ".olean"]
        shared = entry["shared_interpretation"]
        assert shared["nominal_type"] == "LegalCorpusV2.Interpretation"
        assert shared["prelude_module"] == "LegalCorpusV2.Prelude"
        assert shared["prelude_source"]["sha256"] == prelude_sha
        assert shared["prelude_executed_source"]["sha256"] == prelude_sha
        assert shared["prelude_compiled_artifact"]["sha256"] == sha(packet["compiled/LegalCorpusV2/Prelude.olean"])
        assert shared["semantics_module"] == manifest["semantics_module"]
        assert shared["semantics_source"]["sha256"] == semantics_sha
        assert shared["semantics_executed_source"] == {
            "path": semantics_path.replace("project/", "executed-inputs/", 1),
            "bytes": len(packet[semantics_path]), "sha256": semantics_sha,
        }
        semantics_compiled = "compiled/" + manifest["semantics_module"].replace(".", "/") + ".olean"
        assert shared["semantics_compiled_artifact"] == {
            "path": semantics_compiled, "bytes": len(packet[semantics_compiled]),
            "sha256": sha(packet[semantics_compiled]),
        }
        assert shared["semantics_body_sha256"] == manifest["semantics_sha256"]
        assert shared["body_hash_is_complete_module_hash"] is False
        assert entry["native_fragment_binding"] == fragments[entry["role"]]
        assert entry["target_declaration"] == fragments[entry["role"]]["target_declaration"]


@pytest.mark.parametrize("field", ("expected_packet_observation_sha256", "expected_receipt_file_sha256", "expected_bundle_sha256"))
def test_wrong_independent_input_identity_refuses(field, base, inputs, no_execution):
    with pytest.raises(ValueError):
        prepare(base, inputs["fol"], **{field: "0" * 64})


def test_wrong_independent_lineage_identity_refuses(base, inputs, lineages, no_execution):
    with pytest.raises(ValueError):
        validate(lineages["fol"], base, inputs["fol"], expected_lineage_sha256="0" * 64)


@pytest.mark.parametrize("damage", ("mutable_packet", "foreign_lineage", "mutable_claims", "foreign_claim"))
def test_immutable_exact_types_are_required(damage, base, inputs, lineages, no_execution):
    lineage = lineages["fol"]
    if damage == "mutable_packet":
        pairs = list(base.files)
        pairs[0] = (pairs[0][0], bytearray(pairs[0][1]))
        with pytest.raises((ValueError, TypeError)):
            prepare(replace(base, files=tuple(pairs)), inputs["fol"])
        return
    if damage == "foreign_lineage":
        class Foreign:
            lineage_json = lineage.lineage_json
            claims = lineage.claims
        changed = Foreign()
    elif damage == "mutable_claims":
        changed = replace(lineage, claims=list(lineage.claims))
    else:
        changed = replace(lineage, claims=({}, *lineage.claims[1:]))
    with pytest.raises((ValueError, TypeError)):
        validate(changed, base, inputs["fol"])


@pytest.mark.parametrize("damage", ("cross_family", "cross_role", "statement", "premise"))
def test_claim_identity_and_typed_premises_cannot_be_substituted(damage, base, inputs, lineages, no_execution):
    lineage = lineages["fol"]
    claims = list(lineage.claims)
    if damage == "cross_family":
        claims[0] = lineages["tdfol"].claims[0]
    elif damage == "cross_role":
        claims[3], claims[6] = claims[6], claims[3]
    elif damage == "statement":
        claims[0] = replace(claims[0], statement=claims[0].statement.replace("↔", "→"))
    else:
        claims[0] = replace(claims[0], assumptions=(
            replace(claims[0].assumptions[0], statement="False"),
            *claims[0].assumptions[1:],
        ))
    changed = replace(lineage, claims=tuple(claims))
    with pytest.raises(ValueError):
        validate(changed, base, inputs["fol"])


def test_false_cannot_be_replaced_by_zero_in_typed_claim_metadata(
    base, inputs, lineages, no_execution,
):
    original = lineages["fol"]
    claim = original.claims[0]
    metadata = claim.metadata.to_dict()
    assert metadata["proof_authority"] is False
    metadata["proof_authority"] = 0
    changed_claim = replace(claim, metadata=FrozenMap(metadata))
    assert changed_claim.to_dict() == claim.to_dict()  # Python equality alone is insufficient.
    assert changed_claim.digest != claim.digest
    changed = replace(original, claims=(changed_claim, *original.claims[1:]))
    # Supply the actual original complete pin directly. This regression reaches
    # the public validator even if the optional digest helper rejects storage.
    with pytest.raises(ValueError):
        owner.validate_definition_use_preservation_theorem_lineage_v2(
            changed, base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
            expected_lineage_sha256=sha(original.lineage_json.encode("utf-8")),
            **inputs["fol"],
        )


def test_spoofed_claim_owner_identity_refuses_before_descriptor_access(
    base, inputs, lineages, no_execution,
):
    original = lineages["fol"]
    accessed = []
    def poison_claim_id(self):
        accessed.append("claim_id")
        raise AssertionError("spoofed caller descriptor was executed")
    counterfeit_type = type("IRClaim", (), {
        "__module__": IRClaim.__module__,
        "claim_id": property(poison_claim_id),
    })
    changed = replace(original, claims=(counterfeit_type(), *original.claims[1:]))
    assert type(changed.claims[0]).__module__ == IRClaim.__module__
    assert type(changed.claims[0]).__name__ == IRClaim.__name__
    with pytest.raises(ValueError):
        owner.validate_definition_use_preservation_theorem_lineage_v2(
            changed, base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
            expected_lineage_sha256=sha(original.lineage_json.encode("utf-8")),
            **inputs["fol"],
        )
    assert accessed == []


@pytest.mark.parametrize("damage", (
    "theorem_name", "role", "statement_kind", "family", "header", "binder",
    "closure", "compiled_artifact", "byte_offset", "proof_authority",
))
def test_self_resealed_lineage_cannot_replace_current_declaration_identity(
    damage, base, inputs, lineages, no_execution,
):
    lineage = lineages["fol"]
    document = lineage.to_dict()
    entry = document["entries"][0]
    if damage == "theorem_name":
        entry["theorem_name"] += "_different"
    elif damage == "role":
        document["entries"][3]["role"] = "alias"
    elif damage == "statement_kind":
        entry["statement_kind"] = "elaborated_kernel_type"
    elif damage == "family":
        entry["logic_family"] = "fol"
    elif damage == "header":
        entry["declaration_header"] = entry["declaration_header"].replace("↔", "→")
    elif damage == "binder":
        entry["parameter_binders"].pop(0)
    elif damage == "closure":
        entry["declared_import_closure"].pop(0)
    elif damage == "compiled_artifact":
        entry["declared_import_closure"][0]["compiled_artifact"]["sha256"] = "0" * 64
    elif damage == "byte_offset":
        entry["byte_ranges"]["header"]["start_byte"] += 1
    else:
        document["proof_checked"] = True
        document["authority"]["proof"] = True
    changed = replace(lineage, lineage_json=canonical(seal(document)).decode())
    assert changed.lineage_json != lineage.lineage_json
    # The malicious document has a fresh consistent content seal and the
    # caller pins its actual bytes. Only complete current replay can accept it.
    assert changed.to_dict() == seal(changed.to_dict())
    with pytest.raises(ValueError):
        validate(changed, base, inputs["fol"])


@pytest.mark.parametrize("group", ("project", "compiled"))
def test_archived_byte_changes_cannot_preserve_the_old_lineage(
    group, base, inputs, lineages, no_execution,
):
    files = dict(base.files)
    if group == "project":
        path = next(path for path in files if path.startswith("project/LegalCorpusV2/PreservationDonor"))
        files[path] = files[path].replace(b" := by\n  rfl", b" := by\n  exact Eq.refl _", 1)
    else:
        path = next(path for path in files if path.startswith("compiled/LegalCorpusV2/PreservationDonor"))
        files[path] += b" changed compiled identity"
    changed = replace(base, files=tuple(sorted(files.items())))
    # Even caller repinning of the bundle cannot preserve the old observation,
    # source receipt, declaration and compiled-module lineage bindings.
    arguments = inputs["fol"] | {"expected_bundle_sha256": packet_owner.packet_sha256(changed.files)}
    with pytest.raises(ValueError):
        validate(lineages["fol"], changed, arguments)


@pytest.mark.parametrize("damage", ("source", "review", "dependency"))
def test_current_source_review_and_dependencies_are_replayed(damage, base, inputs, no_execution):
    review_inputs = deepcopy(inputs["fol"]["review_inputs"])
    if damage == "source":
        review_inputs["component_raw"] += b"changed source component"
    elif damage == "review":
        review_inputs["policy"]["mode"] = "changed-untrusted-mode"
    else:
        identity = next(iter(review_inputs["observed_artifact_sha256s"]))
        review_inputs["observed_artifact_sha256s"][identity] = None
    with pytest.raises(ValueError):
        prepare(base, inputs["fol"], review_inputs=review_inputs)


def test_review_mutation_after_genuine_public_replay_is_refused(base, inputs, monkeypatch, no_execution):
    reviews = deepcopy(inputs["fol"]["review_inputs"])
    genuine = packet_owner.validate_definition_use_preservation_packet_v2
    completed = []
    def mutate_after_genuine_replay(*args, **kwargs):
        retained = genuine(*args, **kwargs)
        completed.append(retained)
        reviews["injected_after_packet_replay"] = "not among the inputs validated by the genuine reader"
        return retained
    monkeypatch.setattr(packet_owner, "validate_definition_use_preservation_packet_v2", mutate_after_genuine_replay)
    with pytest.raises(ValueError):
        prepare(base, inputs["fol"], review_inputs=reviews)
    assert len(completed) == 1
    assert completed[0].to_dict()["current_preparation_replayed"] is True


def test_to_dict_is_detached_and_outer_dataclass_frozen(lineages):
    lineage = lineages["fol"]
    raw = lineage.lineage_json
    detached = lineage.to_dict()
    detached["training_mask"] = 1
    assert lineage.lineage_json == raw
    assert lineage.to_dict()["training_mask"] == 0
    with pytest.raises((AttributeError, TypeError)):
        lineage.lineage_json = "{}"
