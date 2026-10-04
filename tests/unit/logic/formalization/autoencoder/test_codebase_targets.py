"""Exact captured-source replay and semantic feature collision controls."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import codebase_targets as targets
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as native
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_verification import pipeline
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features


SOURCE = b"def increment(n: int) -> int:\n    return n + 1\n"
CONTRACT = native.IntegerOffsetContract("counter.py", "increment", "n", 1)


def prepare(source=SOURCE, contract=CONTRACT, revision="snapshot:original"):
    return targets.prepare_codebase_targets(source, contract, revision=revision)


def expression(target):
    return target.to_dict()["projections"][0]["expression"]


def details(target):
    return target.to_dict()["validation"][0]["details"]


def test_target_replays_complete_exact_source_and_native_artifacts_without_solving(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("structural target preparation executed a solver")
    monkeypatch.setattr(pipeline, "run_z3_cvc5_differential", forbidden)
    monkeypatch.setattr(native, "execute_integer_offset", forbidden)
    monkeypatch.setattr(native, "run_bounded_stdin_tool", forbidden)
    target = prepare()
    assert targets.validate_codebase_targets(target).canonical_bytes == target.canonical_bytes
    assert target == prepare()
    assert target.domain_id == targets.DOMAIN_ID == "codebase_ir"
    assert target.ready_for_training
    assert len(target.canonical_bytes) < targets.MAX_TARGET_BYTES
    evidence = details(target)
    assert evidence["inputs"] == {"source_ascii": SOURCE.decode(), "contract": CONTRACT.to_dict(),
                                  "revision": "snapshot:original"}
    binding = evidence["binding"]
    assert binding["source_cid"] == cid_for_bytes(SOURCE)
    assert binding["source_sha256"] == hashlib.sha256(SOURCE).hexdigest()
    assert binding["contract_cid"] == CONTRACT.cid
    assert set(evidence["native_artifacts"]) == {"program", "program_contract", "vc_set", "smt_obligation", "compiled"}
    for name, artifact in evidence["native_artifacts"].items():
        assert binding["artifact_cids"][name] == cid_for_structured(artifact)
    compiled = native.compile_integer_offset(SOURCE, CONTRACT, revision="snapshot:original")
    assert evidence["native_artifacts"]["program"] == compiled.pipeline.program.to_dict()
    assert evidence["native_artifacts"]["compiled"] == compiled.to_dict()
    for name in ("qualified", "admitted", "formalized"):
        assert target.to_dict()[name] is False
    for name in ("source_executed", "solver_executed", "kernel_checked", "behavior_authority", "training_executed"):
        assert evidence[name] is False
    assert evidence["assumptions"] == list(native.ASSUMPTIONS)
    assert target.to_dict()["qualification_gaps"]


def test_envelope_is_immutable_and_dictionary_access_is_detached():
    target = prepare()
    with pytest.raises(FrozenInstanceError):
        target.canonical_bytes = b"{}"
    value = target.to_dict()
    value["validation"][0]["details"]["inputs"]["source_ascii"] = "changed"
    assert details(target)["inputs"]["source_ascii"] == SOURCE.decode()


def test_features_retain_both_source_body_and_independent_requested_goal():
    one = prepare()
    wrong_goal = prepare(contract=replace(CONTRACT, offset=2))
    changed_body = prepare(source=SOURCE.replace(b"n + 1", b"n + 2"))
    first, wrong, changed = map(expression, (one, wrong_goal, changed_body))
    assert first["assumptions"] == wrong["assumptions"]
    assert first["goal"] != wrong["goal"]
    assert first["assumptions"] != changed["assumptions"]
    assert first["goal"] == changed["goal"]
    assert first["query_mode"] == "theorem_by_negation"
    assert first["assumptions"][0]["formula"]["sort"] == "Bool"
    assert first["goal"]["arguments"][1]["arguments"][1] == {
        "kind": "int", "sort": "Int", "value": "1", "arguments": []}
    assert all(item.ready_for_training for item in (one, wrong_goal, changed_body))
    assert len({item.source_digest for item in (one, wrong_goal, changed_body)}) == 3


def test_literal_atoms_and_fitted_vectors_are_distinct_without_hash_buckets():
    one = prepare()
    two = prepare(SOURCE.replace(b"n + 1", b"n + 2"), replace(CONTRACT, offset=2))
    assert set(features._tokens(expression(one))) != set(features._tokens(expression(two)))
    space = features.build_feature_space(targets.DOMAIN_ID, [targets.PROJECTION_ID], [one, two])
    vectors, _, coverage = features._matrix(space, [one, two])
    assert vectors[0] != vectors[1]
    assert all(row["unknown_atoms"] == 0 for row in coverage)


def test_unseen_literals_are_reported_as_oov_even_when_projected_vectors_collide():
    one = prepare()
    space = features.build_feature_space(targets.DOMAIN_ID, [targets.PROJECTION_ID], [one])
    three = prepare(SOURCE.replace(b"n + 1", b"n + 3"), replace(CONTRACT, offset=3))
    four = prepare(SOURCE.replace(b"n + 1", b"n + 4"), replace(CONTRACT, offset=4))
    assert set(features._tokens(expression(three))) != set(features._tokens(expression(four)))
    vectors, _, coverage = features._matrix(space, [three, four])
    # Frozen vocabulary reconstruction cannot serve as semantic equivalence.
    assert vectors[0] == vectors[1]
    assert all(row["unknown_atoms"] > 0 for row in coverage)


@pytest.mark.parametrize("source", [
    SOURCE + b"# changed exact bytes\n",
    SOURCE.replace(b"    return", b"\n    return"),
])
def test_nonsemantic_source_edits_change_binding_but_not_features(source):
    old, new = prepare(), prepare(source)
    assert old.digest != new.digest and old.source_digest != new.source_digest
    assert details(old)["binding"]["source_cid"] != details(new)["binding"]["source_cid"]
    assert expression(old) == expression(new)


def test_snapshot_path_and_alpha_names_are_bound_outside_feature_expression():
    original = prepare()
    changed = [
        prepare(revision="snapshot:successor"),
        prepare(contract=replace(CONTRACT, path="nested/other.py")),
        prepare(SOURCE.replace(b"increment", b"renamed").replace(b"(n:", b"(amount:").replace(b"return n", b"return amount"),
                native.IntegerOffsetContract("renamed.py", "renamed", "amount", 1)),
    ]
    for target in changed:
        assert original.source_digest != target.source_digest
        assert expression(original) == expression(target)
    tokens = "\n".join(features._tokens(expression(original)))
    for excluded in (CONTRACT.path, CONTRACT.function_name, "snapshot:original", "source_cid", "span", "sha256"):
        assert excluded not in tokens


def test_ordered_native_operators_and_signed_literals_are_not_folded_away():
    plus = prepare()
    minus = prepare(SOURCE.replace(b"n + 1", b"n - 1"), replace(CONTRACT, offset=-1))
    negative = prepare(SOURCE.replace(b"n + 1", b"n + (-1)"), replace(CONTRACT, offset=-1))
    body = lambda row: expression(row)["assumptions"][0]["formula"]["arguments"][1]
    assert body(plus)["kind"] == "add"
    assert body(minus)["kind"] == "sub"
    assert body(negative)["arguments"][1]["kind"] == "neg"
    assert body(minus)["arguments"][0]["value"] == "parameter"
    assert body(minus)["arguments"][1]["value"] == "1"
    assert len({json.dumps(expression(row), sort_keys=True) for row in (plus, minus, negative)}) == 3


@pytest.mark.parametrize("source", [
    b"def increment(n: int) -> int:\n    if n > 0:\n        return n + 1\n    return n + 2\n",
    b"def increment(n: int) -> int:\n    return n + 1 if n > 0 else n + 2\n",
    b"def increment(n: int) -> int:\n    return n > 1\n",
    b"def increment(n: int) -> int:\n    assert n > 0\n    return n + 1\n",
    b"def increment(n: int) -> int:\n    return callback(n)\n",
    b"import os\n" + SOURCE,
    SOURCE + b"print('must not run')\n",
    b"def increment(n: int = side_effect()) -> int:\n    return n + 1\n",
    b"@decorator\n" + SOURCE,
    b"def increment(n: int) -> int:\n    return n + True\n",
    b"#" * 65537,
])
def test_unsupported_guards_and_effects_reject_before_pipeline(source, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported source reached pipeline")
    monkeypatch.setattr(native.SourceToVerificationPipeline, "run", forbidden)
    with pytest.raises(native.UnsupportedIntegerProfile):
        prepare(source)


@pytest.mark.parametrize("route,value", [
    (("source_digest",), "0" * 64),
    (("projections", 0, "producer_id"), "forged-producer"),
    (("projections", 0, "expression", "goal", "arguments", 1, "arguments", 1, "value"), "2"),
    (("projections", 0, "expression", "assumptions", 0, "formula", "arguments", 1, "kind"), "sub"),
    (("validation", 0, "details", "inputs", "revision"), "snapshot:other"),
    (("validation", 0, "details", "inputs", "source_ascii"), SOURCE.decode() + "# stale\n"),
    (("validation", 0, "details", "inputs", "contract", "offset"), 2),
    (("validation", 0, "details", "binding", "source_cid"), "forged"),
    (("validation", 0, "details", "binding", "artifact_cids", "program"), "forged"),
    (("validation", 0, "details", "native_artifacts", "compiled", "body_offset"), True),
    (("validation", 0, "details", "native_artifacts", "compiled", "kernel_checked"), 0),
    (("validation", 0, "details", "solver_executed"), 0),
    (("validation", 0, "details", "behavior_authority"), True),
    (("validation", 0, "details", "assumptions"), []),
    (("qualification_gaps",), []),
])
def test_every_provenance_semantic_or_authority_mutation_requires_exact_replay(route, value):
    wire = prepare().to_dict()
    cursor = wire
    for component in route[:-1]:
        cursor = cursor[component]
    cursor[route[-1]] = value
    forged = DomainTargetEnvelope.from_dict(wire)
    with pytest.raises(targets.CodebaseTargetError, match="producer replay"):
        targets.validate_codebase_targets(forged)


def test_rehashing_a_forged_native_artifact_does_not_replace_source_replay():
    wire = prepare().to_dict()
    evidence = wire["validation"][0]["details"]
    evidence["native_artifacts"]["program"]["metadata"]["invented"] = True
    evidence["binding"]["artifact_cids"]["program"] = cid_for_structured(evidence["native_artifacts"]["program"])
    wire["source_digest"] = hashlib.sha256(cid_for_structured(evidence["binding"]).encode()).hexdigest()
    with pytest.raises(targets.CodebaseTargetError, match="producer replay"):
        targets.validate_codebase_targets(DomainTargetEnvelope.from_dict(wire))


def test_validator_bounds_before_recompiling_and_requires_typed_envelope(monkeypatch):
    target = prepare()
    with pytest.raises(targets.CodebaseTargetError, match="exact DomainTargetEnvelope"):
        targets.validate_codebase_targets(target.to_dict())
    wire = target.to_dict()
    wire["validation"][0]["details"]["padding"] = "x" * targets.MAX_TARGET_BYTES
    oversized = DomainTargetEnvelope.from_dict(wire)
    def forbidden(*args, **kwargs):
        pytest.fail("oversized target reached source replay")
    monkeypatch.setattr(native, "compile_integer_offset", forbidden)
    with pytest.raises(targets.CodebaseTargetError, match="byte bound"):
        targets.validate_codebase_targets(oversized)


def test_validator_reconstructs_frozen_bytes_after_bypassed_immutability():
    target = prepare()
    object.__setattr__(target, "canonical_bytes", b"{}")
    with pytest.raises(ValueError):
        targets.validate_codebase_targets(target)
