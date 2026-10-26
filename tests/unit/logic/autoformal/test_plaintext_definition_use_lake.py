"""Parent conditional projects retain complete custody and no Lean authority.

Inputs are authored plaintext and genuine synthetic signatures built by the
installed parent-use/review fixtures. These tests neither build Lean nor train
or invoke a model. Official and native entrypoints remain separate.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_use_review_v2 as review
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parents
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as owner
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


TOOLCHAIN = "leanprover/lean4:v4.34.1"


def helper(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PARENT = helper("test_plaintext_definition_use_review.py", "parent_review_for_parent_lake")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sealed(value):
    return contracts.seal_record({key: item for key, item in value.items()
                                 if key not in {"record_cid", "cid_scope"}})


def review_arguments(support, signed):
    args, kwargs = support.signing.assessment_arguments(signed)
    return dict(zip(("subject", "registry", "policy", "reviews", "dependency_manifest"),
                    args, strict=True)) | kwargs


def refresh_assessment(support, signed):
    inputs = review_arguments(support, signed)
    report = review.assess_parent_definition_use_reviews_v1(**inputs)
    raw = wire(report) + b"\n"
    return dict(signed=signed, assessment=report, assessment_raw=raw,
                expected_assessment_file_sha256=sha(raw), review_inputs=inputs,
                toolchain=TOOLCHAIN)


def make_data(support, path, *, family="fol"):
    component = _PARENT.component(support, path, family=family)
    materialized = _PARENT.materialize(component)
    domain = SimpleNamespace(CLAIM_SCHEMA=review.PARENT_CLAIM_SCHEMA,
                             ACTION=review.PARENT_ACTION, AUDIENCE=review.PARENT_AUDIENCE)
    signed = support.signing.signed.__wrapped__(domain, materialized)
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    support.signing.refresh(signed)
    return refresh_assessment(support, signed)


def arguments(data):
    return {key: data[key] for key in ("assessment_raw", "expected_assessment_file_sha256",
                                     "review_inputs", "toolchain")}


def prepare(data):
    return owner.prepare_parent_definition_use_corpus_v1(**arguments(data))


def validate(prepared, data):
    return owner.validate_parent_definition_use_corpus_v1(prepared, **arguments(data))


def modified_manifest(prepared, manifest):
    return replace(prepared, manifest_json=canonical_dag_json_bytes(sealed(manifest)).decode())


@pytest.fixture(scope="module")
def support():
    return _PARENT.fixtures.__wrapped__()


@pytest.fixture(scope="module")
def base(support, tmp_path_factory):
    return make_data(support, tmp_path_factory.mktemp("parent-lake-originals", numbered=False))


@pytest.fixture
def case(base):
    return deepcopy(base)


@pytest.fixture(scope="module")
def frozen(base):
    return prepare(base)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_full_parent_joint_context_and_conditional_project_without_execution(
        support, base, tmp_path, family, monkeypatch):
    data = base if family == "fol" else make_data(support, tmp_path, family=family)
    def forbidden(*args, **kwargs):
        pytest.fail("parent project preparation must not execute or probe a toolchain")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    before = deepcopy(data["review_inputs"])
    prepared = prepare(data)
    manifest, files = prepared.to_dict(), dict(prepared.files)
    component = data["signed"]["component"]["record"]
    prep = data["review_inputs"]["subject"]["native_binding"]
    assert type(prepared) is owner.DefinitionUseCorpusPreparation
    assert manifest["schema"] == owner.PARENT_SCHEMA != owner.SCHEMA
    assert manifest["profile"] == owner.PARENT_PROFILE != owner.PROFILE
    assert manifest["review_intake_binding"]["schema"] == owner.PARENT_INPUT_BINDING_SCHEMA
    assert files["lean-toolchain"] == TOOLCHAIN + "\n"
    lake = tomllib.loads(files["lakefile.toml"])
    assert lake["version"] == "0.1.0"
    assert lake["lean_lib"] == [{"name": "legal", "roots": ["LegalCorpusParent"]}]
    assert len(prepared.files) == len(files) == 9
    assert "parent-input-bindings.json" in files and "v2-input-bindings.json" not in files
    assert manifest["file_sha256"] == {name: sha(text.encode()) for name, text in files.items()}
    assert json.loads(files["parent-input-bindings.json"]) == manifest["review_intake_binding"]
    fragments = {row["role"]: row for row in manifest["native_fragments"]}
    expected = {role: component[role + "_native"]["native_ast"] for role in ("alias", "joint")}
    for role in ("donor", "consumer"):
        expected[role] = data["signed"]["component"]["case"][role]["candidate"]["definition_record"]["native_ast"]
    assert list(fragments) == ["donor", "consumer", "alias", "joint"]
    for role, ast in expected.items():
        fragment = fragments[role]
        assert fragment["native"]["native_ast"] == ast
        assert fragment["native"]["exact_native_ast_roundtrip"] is True
        assert fragment["native"]["backend_executed"] is False
        assert fragment["native"]["lean_body"] in files[fragment["module"].replace(".", "/") + ".lean"]
    donor, consumer, alias, joint = [fragments[role]["module"] for role in ("donor", "consumer", "alias", "joint")]
    expected_imports = {"LegalCorpusParent.Prelude": [], donor: ["LegalCorpusParent.Prelude"],
                        consumer: ["LegalCorpusParent.Prelude"], alias: [donor, consumer],
                        joint: [donor, consumer, alias], "LegalCorpusParent": [joint]}
    assert manifest["expected_modules"] == ["LegalCorpusParent.Prelude", donor, consumer,
                                            alias, joint, "LegalCorpusParent"]
    assert manifest["module_imports"] == expected_imports
    seen = set()
    for module in manifest["expected_modules"]:
        body = files[module.replace(".", "/") + ".lean"]
        assert re.findall(r"^import ([A-Za-z0-9_.]+)$", body, re.M) == expected_imports[module]
        assert set(expected_imports[module]) <= seen
        seen.add(module)
    binding = manifest["review_source_binding"]
    assert binding == {key: prep[key] for key in ("original_definitions", "contexts", "binding_record",
                                                  "alias_record", "scope_binding", "context_slot_ids", "review_contract")}
    assert binding["contexts"] == component["context_population"]
    assert binding["binding_record"]["body_roles"] == ["definition_body/0000", "definition_body/0001"]
    assert len(set(binding["binding_record"]["body_occurrence_cids"])) == 2
    assert all(row["source_version"]["edition"] == parents.UNDECLARED_EDITION
               for row in binding["original_definitions"])
    assert "declared_applicability" not in binding["scope_binding"]
    assert binding["alias_record"]["assumed_not_proved"] is True
    assert manifest["review_dependency_manifest"] == data["review_inputs"]["dependency_manifest"]
    assert manifest["review_prerequisites_satisfied_under_selected_trust"] is True
    assert manifest["review_blockers"] == data["assessment"]["blockers"]
    assert all(manifest[key] is False for key in owner.PARENT_FALSE_FLAGS)
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert manifest["preparation_only"] is True and manifest["lean_compilation_status"] == "not_run"
    alias_text = files[alias.replace(".", "/") + ".lean"]
    joint_text = files[joint.replace(".", "/") + ".lean"]
    assert "(hDonor :" in alias_text and "(hAlias :" in alias_text
    assert "(hAlias entity).trans (hDonor entity)" in alias_text
    assert all("(h" + role + " :" in joint_text for role in ("Donor", "Consumer", "Alias"))
    assert len(manifest["conditional_theorems"]) == 3
    assert any("assumes the exact donor definition and explicit alias" in x for x in manifest["theorem_assumptions"])
    assert validate(prepared, data) == prepared and data["review_inputs"] == before


@pytest.mark.parametrize("damage", ["synthetic", "context_declaration"])
def test_fresh_blocked_parent_assessments_remain_blocked_in_candidate_text(support, case, damage):
    signed = case["signed"]
    if damage == "synthetic":
        signed["registry"]["mode"] = signed["policy"]["mode"] = "synthetic_fixture"
    else:
        signed["reviews"][0]["context_closure"]["obligations"].pop()
    support.signing.refresh(signed)
    current = refresh_assessment(support, signed)
    manifest = prepare(current).to_dict()
    assert manifest["review_evidence_status"] == current["assessment"]["evidence_assessment_status"]
    assert manifest["review_blockers"] == current["assessment"]["blockers"]
    assert manifest["review_prerequisites_satisfied_under_selected_trust"] is False
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert all(manifest[key] is False for key in owner.PARENT_FALSE_FLAGS)


@pytest.mark.parametrize("damage", ["revocation", "observed_artifact"])
def test_saved_assessment_cannot_hide_fresh_revocation_or_dependency_change(support, case, damage):
    signed = case["signed"]
    if damage == "revocation":
        signed["registry"]["keys"][0]["revoked_at_utc"] = support.signing.NOW
        support.signing.refresh(signed)
    else:
        identity = signed["preparation"]["required_dependency_ids"][-1]
        signed["observed_artifact_sha256s"][identity] = "0" * 64
    case["review_inputs"] = review_arguments(support, signed)
    with pytest.raises(ValueError):
        prepare(case)
    current = refresh_assessment(support, signed)
    manifest = prepare(current).to_dict()
    assert manifest["review_prerequisites_satisfied_under_selected_trust"] is False
    assert manifest["review_blockers"] == current["assessment"]["blockers"]
    assert manifest["execution_handoff"]["build_eligible"] is False


def test_genuinely_resigned_old_domain_cannot_enter_parent_preparation(support, case):
    case["signed"]["reviews"][0]["audience"] = review.AUDIENCE
    support.signing.refresh(case["signed"])
    case["review_inputs"] = review_arguments(support, case["signed"])
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["physical_source", "ordered_context"])
def test_parent_preparation_replays_actual_original_source_and_context(support, tmp_path, damage):
    data = make_data(support, tmp_path)
    endpoint = data["review_inputs"]["use_inputs"]["consumer_evidence_inputs"]
    if damage == "physical_source":
        descriptor = endpoint["parent_inputs"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
        path = Path(descriptor["local_path"])
        path.write_bytes(path.read_bytes() + b"\nchanged isolated parent source")
    else:
        endpoint["context_inputs"].pop()
        endpoint["expected_context_population"].pop()
    with pytest.raises(ValueError):
        prepare(data)


def test_rehashed_assessment_joint_identity_cannot_replace_fresh_full_ast(case):
    report = deepcopy(case["assessment"])
    report["joint_ast_sha256"] = "0" * 64
    report["assessment_sha256"] = signatures.digest({key: value for key, value in report.items()
                                                    if key != "assessment_sha256"})
    case["assessment_raw"] = wire(report) + b"\n"
    case["expected_assessment_file_sha256"] = sha(case["assessment_raw"])
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["authority", "scope"])
def test_resealed_parent_manifest_does_not_replace_source_or_authority(frozen, base, damage):
    manifest = frozen.to_dict()
    if damage == "authority":
        manifest["governing_edition_verified"] = True
    else:
        manifest["review_source_binding"]["scope_binding"] = {}
    with pytest.raises(ValueError):
        validate(modified_manifest(frozen, manifest), base)


def test_rehashed_file_manifest_cannot_remove_the_alias_hypothesis(frozen, base):
    manifest, files = frozen.to_dict(), dict(frozen.files)
    alias = next(row["module"] for row in manifest["native_fragments"] if row["role"] == "alias")
    path = alias.replace(".", "/") + ".lean"
    assert "(hAlias :" in files[path]
    files[path] = files[path].replace("(hAlias :", "(unsignedAlias :", 1)
    manifest["file_sha256"] = {name: sha(body.encode()) for name, body in files.items()}
    forged = replace(modified_manifest(frozen, manifest), files=tuple(sorted(files.items())))
    with pytest.raises(ValueError):
        validate(forged, base)


def test_parent_project_transport_is_closed_pinned_and_never_overwrites(frozen, base, tmp_path):
    directory = tmp_path / "project"
    assert owner.write_parent_definition_use_corpus_v1(frozen, directory, **arguments(base)) == frozen.to_dict()
    raw = (directory / "corpus-manifest.json").read_bytes()
    assert raw == frozen.manifest_json.encode()
    assert owner.load_parent_definition_use_corpus_v1(directory,
        expected_manifest_sha256=sha(raw), **arguments(base)) == frozen
    before = {str(x.relative_to(directory)): x.read_bytes() for x in directory.rglob("*") if x.is_file()}
    assert set(before) == {"corpus-manifest.json", *dict(frozen.files)}
    with pytest.raises((ValueError, OSError)):
        owner.write_parent_definition_use_corpus_v1(frozen, directory, **arguments(base))
    assert before == {str(x.relative_to(directory)): x.read_bytes() for x in directory.rglob("*") if x.is_file()}


@pytest.mark.parametrize("damage", ["extra", "directory_symlink", "manifest_pin"])
def test_parent_loader_refuses_unclosed_or_unpinned_transport(frozen, base, tmp_path, damage):
    directory = tmp_path / "project"
    # The module fixture is a genuine prepared project. Avoid repeating the
    # public writer's validation/readback just to arrange negative loader data;
    # each assertion below still invokes full public loading/original replay.
    directory.mkdir()
    for name, body in frozen.files:
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        destination = directory / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body.encode("utf-8"))
    (directory / "corpus-manifest.json").write_bytes(frozen.manifest_json.encode("utf-8"))
    pin = sha((directory / "corpus-manifest.json").read_bytes())
    load_directory, descriptor = directory, None
    try:
        if damage == "extra":
            (directory / "Foreign.lean").write_text("def fabricated : Prop := True\n")
        elif damage == "directory_symlink":
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            load_directory = Path("/proc") / str(os.getpid()) / "fd" / str(descriptor)
            assert load_directory.is_symlink()
        else:
            pin = "0" * 64
        with pytest.raises((ValueError, OSError)):
            owner.load_parent_definition_use_corpus_v1(load_directory,
                expected_manifest_sha256=pin, **arguments(base))
    finally:
        # The genuine proc descriptor alias creates no owned inventory member.
        if descriptor is not None:
            os.close(descriptor)


def test_official_preparation_validation_and_native_route_reject_parent(frozen, base):
    with pytest.raises(ValueError):
        owner.prepare_definition_use_corpus_v2(**arguments(base))
    with pytest.raises(ValueError):
        owner.validate_definition_use_corpus_v2(frozen, **arguments(base))
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
    with pytest.raises(ValueError):
        native.validate_definition_use_native_v2(frozen,
            expected_preparation_sha256=native.preparation_sha256(frozen), **arguments(base))


def test_parent_route_refuses_an_actual_official_assessment():
    official = helper("test_legal_corpus_definition_use_lake_v2.py", "official_case_for_parent_lake")
    data = official.assessment_data()
    with pytest.raises(ValueError):
        prepare(data)


@pytest.mark.parametrize("route", ["prepare", "validate", "load", "write"])
def test_parent_total_budget_refuses_before_review_or_optional_owner_dispatch(
        case, frozen, tmp_path, monkeypatch, route):
    def forbidden(*args, **kwargs):
        pytest.fail("complete parent budget must refuse before review or native dispatch")
    monkeypatch.setattr(owner, "MAX_INPUT_BYTES", 1)
    monkeypatch.setattr(owner, "_owners", forbidden)
    monkeypatch.setattr(review, "validate_parent_definition_use_review_assessment_v1", forbidden)
    directory = tmp_path / "never-created"
    with pytest.raises(ValueError):
        if route == "prepare":
            prepare(case)
        elif route == "validate":
            validate(frozen, case)
        elif route == "load":
            owner.load_parent_definition_use_corpus_v1(directory,
                expected_manifest_sha256="0" * 64, **arguments(case))
        else:
            owner.write_parent_definition_use_corpus_v1(frozen, directory, **arguments(case))
    assert not directory.exists()


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_auth_time_mutation_after_genuine_render_is_not_returned(case, monkeypatch, target):
    before = deepcopy(case["review_inputs"])
    genuine = owner._render
    def render_then_mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        inputs = case["review_inputs"] if target == "caller" else args[1]
        inputs["at_time_utc"] = "2099-01-01T00:00:00Z"
        return result
    monkeypatch.setattr(owner, "_render", render_then_mutate)
    with pytest.raises(ValueError):
        prepare(case)
    if target == "detached":
        assert case["review_inputs"] == before


def test_offered_preparation_mutation_after_genuine_regeneration_is_not_returned(
        frozen, base, monkeypatch):
    offered = replace(frozen)
    original = offered.manifest_json
    genuine = owner._render
    def render_then_mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        object.__setattr__(offered, "manifest_json", original + " ")
        return result
    monkeypatch.setattr(owner, "_render", render_then_mutate)
    with pytest.raises(ValueError):
        validate(offered, base)
    assert frozen.manifest_json == original


# Bounded historical public-input transport. These codec controls deliberately
# need no genuine fixture, optional backend, model, subprocess or source replay.
def parent_replay_transport_guards(monkeypatch):
    import builtins
    from ipfs_datasets_py.logic.backends import process
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2

    def forbidden(*args, **kwargs):
        pytest.fail("parent replay transport cannot execute a model, process or toolchain")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(legal_corpus_definition_use_native_v2, "_installed_toolchain", forbidden)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {
                "torch", "transformers", "sentence_transformers", "llama_cpp", "litellm", "openai"}:
            forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


@pytest.fixture
def parent_replay_codec_guard(monkeypatch):
    parent_replay_transport_guards(monkeypatch)


@pytest.mark.parametrize("value,expected", [
    (None, b"n"),
    (True, b"t"),
    (False, b"f"),
    (b"\x00\xff", b"b2:\x00\xff"),
    ("Café雪", b"s8:Caf\xc3\xa9\xe9\x9b\xaa"),
    (-(2**63), b"i20:-9223372036854775808"),
    (2**63 - 1, b"i19:9223372036854775807"),
    ({"a": [None, True, False, b"xy", -1, -0.0]},
     b"d1:s1:al6:ntfb2:xyi2:-1r4:-0.0"),
], ids=["null", "true", "false", "raw-bytes", "unicode", "int-min", "int-max", "mixed-golden"])
def test_parent_replay_codec_exact_original_typed_frames(parent_replay_codec_guard, value, expected):
    payload = owner.encode_parent_replay_value_v1(value)
    assert payload == expected
    assert sha(payload) == owner._parent_commitment(value)
    restored = owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=sha(expected))
    assert type(restored) is type(value)
    assert restored == value
    assert owner.encode_parent_replay_value_v1(restored) == expected


def test_parent_replay_codec_type_identity_negative_zero_and_dict_order(parent_replay_codec_guard):
    import math

    values = [None, False, True, 0, 1, 0.0, -0.0, "0", b"0"]
    frames = [owner.encode_parent_replay_value_v1(value) for value in values]
    assert len(set(frames)) == len(values)
    for value, payload in zip(values, frames, strict=True):
        restored = owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=sha(payload))
        assert type(restored) is type(value)
        if type(value) is float:
            assert math.copysign(1.0, restored) == math.copysign(1.0, value)
    assert owner.encode_parent_replay_value_v1({"z": 0, "a": 1}) == b"d2:s1:ai1:1s1:zi1:0"
    assert owner._parent_commitment({"z": 0, "a": 1}) == sha(b"d2:s1:ai1:1s1:zi1:0")


def test_parent_replay_codec_returns_detached_ordinary_containers(parent_replay_codec_guard):
    value = {"nested": [{"bytes": b"original", "text": "unchanged"}]}
    payload = owner.encode_parent_replay_value_v1(value)
    restored = owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=sha(payload))
    restored["nested"][0]["text"] = "changed"
    assert value["nested"][0]["text"] == "unchanged"
    assert owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=sha(payload)) == value


@pytest.mark.parametrize("payload", [
    b"x", b"nt", b"s2:a", b"b01:x", b"l-1:",
    b"d2:s1:ans1:an", b"d2:s1:bns1:an", b"d1:b1:an", b"s1:\xff",
    b"i2:01", b"i19:9223372036854775808", b"r3:NaN", b"r3:1e0",
    b"l1000000:", b"l" + b"9" * 40 + b":", b"l1:" * 49 + b"n", b"d1:s4097:" + b"a" * 4097 + b"n",
], ids=["unknown", "trailing", "truncated", "zero-length-prefix", "negative-count",
        "duplicate-key", "unsorted-keys", "bytes-key", "bad-utf8", "integer-leading-zero",
        "integer-overflow", "nonfinite-float", "noncanonical-float", "declared-node-overflow", "huge-header",
        "depth-overflow", "key-overflow"])
def test_parent_replay_codec_refuses_noncanonical_or_overbound_frames(parent_replay_codec_guard, payload):
    # The largest malformed fixture is ~4 KiB; an oversized declared count must
    # fail before attempting to allocate its claimed million-child population.
    with pytest.raises(contracts.CorpusContractError):
        owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=sha(payload))


@pytest.mark.parametrize("kind", ["tuple", "mutable-bytes", "dict-subclass", "nonstring-key", "nan"])
def test_parent_replay_codec_refuses_nonordinary_input(parent_replay_codec_guard, kind):
    class DerivedDict(dict):
        pass

    value = {"tuple": (), "mutable-bytes": bytearray(b"x"), "dict-subclass": DerivedDict(a=1),
             "nonstring-key": {1: "x"}, "nan": float("nan")}[kind]
    with pytest.raises(contracts.CorpusContractError):
        owner.encode_parent_replay_value_v1(value)


@pytest.mark.parametrize("maximum", [True, 0, 1.0, 64 * 1024**2 + 1],
                         ids=["bool", "zero", "float", "raised"])
def test_parent_replay_codec_strict_lower_only_wire_limit(parent_replay_codec_guard, maximum):
    with pytest.raises(contracts.CorpusContractError):
        owner.encode_parent_replay_value_v1(None, max_bytes=maximum)
    with pytest.raises(contracts.CorpusContractError):
        owner.decode_parent_replay_value_v1(b"n", expected_payload_sha256=sha(b"n"), max_bytes=maximum)


@pytest.mark.parametrize("damage", ["wrong-pin", "uppercase-pin", "mutable-payload"])
def test_parent_replay_codec_requires_independent_pin_and_immutable_bytes(parent_replay_codec_guard, damage):
    payload, pin = b"d1:s1:an", sha(b"d1:s1:an")
    if damage == "wrong-pin":
        pin = "0" * 64
    elif damage == "uppercase-pin":
        pin = pin.upper()
    else:
        payload = bytearray(payload)
    with pytest.raises(contracts.CorpusContractError):
        owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=pin)


@pytest.mark.parametrize("bound", ["wire", "expanded"])
def test_parent_replay_codec_enforces_small_wire_and_expanded_bounds(parent_replay_codec_guard, monkeypatch, bound):
    value = "\x00" * 8
    payload = b"s8:" + b"\x00" * 8
    if bound == "expanded":
        monkeypatch.setattr(owner, "MAX_INPUT_BYTES", 16)
        maximum = len(payload)
    else:
        maximum = len(payload) - 1
    with pytest.raises(contracts.CorpusContractError):
        owner.encode_parent_replay_value_v1(value, max_bytes=maximum)
    with pytest.raises(contracts.CorpusContractError):
        owner.decode_parent_replay_value_v1(payload, expected_payload_sha256=sha(payload), max_bytes=maximum)
