"""Contract vectors for scoped relation and equivalence claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_relations import (
    FORBIDDEN_RELATION_KINDS,
    RELATION_INVALIDATION_SCHEMA,
    RELATION_KIND_FAMILY,
    RELATION_SCOPE_SCHEMA,
    RELATION_VALIDATION_RECEIPT_INTERFACE,
    RELATION_VALIDATION_RECEIPT_SCHEMA,
    SCOPED_PROGRAM_RELATION_INTERFACE,
    SCOPED_PROGRAM_RELATION_SCHEMA,
    SCOPED_RELATION_FAMILIES,
    ContradictionDisposition,
    ProgramRelationClaim,
    ProgramRelationError,
    RelationAuthorityStatus,
    RelationFamily,
    RelationInvalidation,
    RelationInvalidationKind,
    RelationKind,
    RelationScope,
    RelationScopeKind,
    RelationValidationReceipt,
    RelationValidationVerdict,
    ScopedProgramRelation,
    attempt_ex_falso_admission,
    canonical_relation_bytes,
    decode_relation_record,
    detect_conflicts,
    invalidate_by_assumption,
    invalidate_by_environment,
    invalidate_by_scope,
    invalidate_relation,
    is_authoritative_status,
    load_payload_schema,
    loads_relation_json,
    may_influence_planning,
    promote_relation,
    relation_cid_for,
    relation_family_for,
    validate_relation_claim,
    validate_relation_set,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "program-relation.payload.schema.json"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _scope(**overrides: Any) -> RelationScope:
    fields: dict[str, Any] = {
        "scope_kind": RelationScopeKind.MODULE,
        "language": "python",
        "subject_cids": [_cid("mod.a"), _cid("mod.b")],
        "theory_or_policy_cid": _cid("theory-v1"),
        "environment_binding_cid": _cid("env-v1"),
        "assumption_cids": [_cid("asm-b"), _cid("asm-a")],
        "unavailable_dimensions": ("native_stack",),
    }
    fields.update(overrides)
    return RelationScope(**fields)


def _claim(scope: RelationScope | None = None, **overrides: Any) -> ProgramRelationClaim:
    bound = scope or _scope()
    fields: dict[str, Any] = {
        "relation_kind": RelationKind.EQUALITY,
        "left_cid": _cid("left"),
        "right_cid": _cid("right"),
        "scope_cid": bound.scope_cid,
        "theory_or_policy_cid": bound.theory_or_policy_cid,
        "environment_binding_cid": bound.environment_binding_cid,
        "authority_status": RelationAuthorityStatus.CANDIDATE,
        "assumption_cids": bound.assumption_cids,
        "evidence_cids": (),
        "invalidator_cids": (),
        "superseded_by_cid": None,
    }
    fields.update(overrides)
    return ProgramRelationClaim(**fields)


def _proved(scope: RelationScope | None = None, **overrides: Any) -> ProgramRelationClaim:
    fields: dict[str, Any] = {
        "authority_status": RelationAuthorityStatus.PROVED,
        "evidence_cids": [_cid("proof-1")],
    }
    fields.update(overrides)
    return _claim(scope, **fields)


def _sample_payloads() -> list[dict[str, Any]]:
    scope = _scope()
    equality = ProgramRelationClaim.from_scope(
        scope,
        relation_kind=RelationKind.EQUALITY,
        left_cid=_cid("left"),
        right_cid=_cid("right"),
        authority_status=RelationAuthorityStatus.PROVED,
        evidence_cids=[_cid("ev-2"), _cid("ev-1")],
    )
    contradiction = ProgramRelationClaim.from_scope(
        scope,
        relation_kind=RelationKind.CONTRADICTION,
        left_cid=_cid("left"),
        right_cid=_cid("right"),
        authority_status=RelationAuthorityStatus.PROVED,
        evidence_cids=[_cid("cex-1")],
    )
    stale, invalidation = invalidate_relation(
        equality,
        RelationInvalidationKind.ENVIRONMENT_CHANGED,
        [_cid("env-v2")],
    )
    superseded_source = _proved(scope, relation_kind=RelationKind.REFINEMENT)
    replacement = _proved(
        scope,
        relation_kind=RelationKind.REFINEMENT,
        evidence_cids=[_cid("proof-2")],
    )
    superseded, supersession = invalidate_relation(
        superseded_source,
        RelationInvalidationKind.SUPERSEDED,
        [_cid("newer-proof")],
        successor_claim_cid=replacement.relation_claim_cid,
    )
    admitted = validate_relation_claim(equality)
    conflict = validate_relation_claim(equality, peer_claims=[contradiction])
    abstain = attempt_ex_falso_admission(contradiction, replacement)
    return [
        scope.to_dict(),
        equality.to_dict(),
        contradiction.to_dict(),
        stale.to_dict(),
        invalidation.to_dict(),
        superseded.to_dict(),
        supersession.to_dict(),
        admitted.to_dict(),
        conflict.to_dict(),
        abstain.to_dict(),
    ]


def test_public_interfaces_are_versioned() -> None:
    assert SCOPED_PROGRAM_RELATION_INTERFACE == "ScopedProgramRelation@1"
    assert RELATION_VALIDATION_RECEIPT_INTERFACE == "RelationValidationReceipt@1"
    assert ProgramRelationClaim.INTERFACE == SCOPED_PROGRAM_RELATION_INTERFACE
    assert ProgramRelationClaim.SCHEMA == SCOPED_PROGRAM_RELATION_SCHEMA
    assert RelationValidationReceipt.INTERFACE == RELATION_VALIDATION_RECEIPT_INTERFACE
    assert RelationValidationReceipt.SCHEMA == RELATION_VALIDATION_RECEIPT_SCHEMA
    assert RelationScope.SCHEMA == RELATION_SCOPE_SCHEMA
    assert RelationInvalidation.SCHEMA == RELATION_INVALIDATION_SCHEMA
    assert ScopedProgramRelation is ProgramRelationClaim


def test_closed_enums_cover_scoped_families_and_authority_lifecycle() -> None:
    kinds = {item.value for item in RelationKind}
    assert kinds == {
        "equality",
        "refinement",
        "entailment",
        "contradiction",
        "compatibility",
        "alpha_equivalence",
        "structural_equivalence",
        "logical_equivalence",
        "behavioral_equivalence",
        "observational_equivalence",
        "intent",
        "transition_behavior",
    }
    statuses = {item.value for item in RelationAuthorityStatus}
    assert statuses == {
        "candidate",
        "asserted",
        "validated",
        "proved",
        "refuted",
        "unknown",
        "stale",
        "superseded",
    }
    families = {RELATION_KIND_FAMILY[kind] for kind in kinds}
    assert SCOPED_RELATION_FAMILIES <= families
    assert relation_family_for("logical_equivalence") == RelationFamily.EQUIVALENCE.value
    assert relation_family_for(RelationKind.EQUALITY) == RelationFamily.EQUALITY.value
    assert "similarity" not in kinds
    assert "similar" in FORBIDDEN_RELATION_KINDS
    assert is_authoritative_status("proved") is True
    assert is_authoritative_status(RelationAuthorityStatus.CANDIDATE) is False


def test_canonical_identity_vectors_are_stable_and_rehash() -> None:
    scope = _scope()
    expected_scope = {
        "schema": RELATION_SCOPE_SCHEMA,
        "scope_kind": "module",
        "language": "python",
        "subject_cids": sorted([_cid("mod.a"), _cid("mod.b")]),
        "assumption_cids": sorted([_cid("asm-a"), _cid("asm-b")]),
        "theory_or_policy_cid": _cid("theory-v1"),
        "environment_binding_cid": _cid("env-v1"),
        "unavailable_dimensions": ["native_stack"],
    }
    assert scope.identity_payload() == expected_scope
    assert scope.scope_cid == cid_for_structured(expected_scope)
    assert scope.canonical_bytes() == canonical_dag_json_bytes(expected_scope)
    claim = ProgramRelationClaim.from_scope(
        scope,
        relation_kind="equality",
        left_cid=_cid("left"),
        right_cid=_cid("right"),
        assumption_cids=[_cid("asm-b"), _cid("asm-a")],
    )
    expected_claim = {
        "schema": SCOPED_PROGRAM_RELATION_SCHEMA,
        "relation_kind": "equality",
        "left_cid": _cid("left"),
        "right_cid": _cid("right"),
        "scope_cid": scope.scope_cid,
        "assumption_cids": sorted([_cid("asm-a"), _cid("asm-b")]),
        "theory_or_policy_cid": _cid("theory-v1"),
        "environment_binding_cid": _cid("env-v1"),
        "evidence_cids": [],
        "invalidator_cids": [],
        "authority_status": "candidate",
        "superseded_by_cid": None,
    }
    assert claim.identity_payload() == expected_claim
    assert claim.relation_claim_cid == relation_cid_for(expected_claim)
    assert claim.canonical_bytes() == canonical_relation_bytes(expected_claim)
    shuffled = ProgramRelationClaim.from_scope(
        scope,
        relation_kind="equality",
        left_cid=_cid("left"),
        right_cid=_cid("right"),
        assumption_cids=[_cid("asm-a"), _cid("asm-b")],
    )
    assert shuffled.relation_claim_cid == claim.relation_claim_cid


def test_records_round_trip_and_rehash() -> None:
    for payload in _sample_payloads():
        record = decode_relation_record(payload)
        assert record.to_dict() == payload
        claimed = payload[record.CID_FIELD]
        assert decode_and_recompute_structured(claimed, record.identity_payload()) == claimed
        again = json.loads(json.dumps(payload, sort_keys=True))
        assert decode_relation_record(again).to_dict() == payload


def test_unknown_fields_versions_and_forged_cids_fail_closed() -> None:
    payload = _claim().to_dict()
    with pytest.raises(ProgramRelationError, match="unknown fields"):
        ProgramRelationClaim.from_dict({**payload, "similarity": 0.9})
    with pytest.raises(ProgramRelationError, match="unknown fields"):
        ProgramRelationClaim.from_dict({**payload, "score": 1})
    with pytest.raises(ProgramRelationError, match="schema version"):
        ProgramRelationClaim.from_dict(
            {**payload, "schema": SCOPED_PROGRAM_RELATION_SCHEMA.replace("@1", "@99")}
        )
    forged = dict(payload)
    forged["relation_claim_cid"] = _cid("forged")
    with pytest.raises(ProgramRelationError, match="does not verify"):
        ProgramRelationClaim.from_dict(forged)
    with pytest.raises(ProgramRelationError, match="unsupported relation schema"):
        decode_relation_record({"schema": "not-a-payload", "x": 1})


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected() -> None:
    with pytest.raises(ProgramRelationError, match="duplicate JSON key"):
        loads_relation_json('{"a":1,"a":2}')
    with pytest.raises(ProgramRelationError, match="nonfinite"):
        loads_relation_json("NaN")
    with pytest.raises(ProgramRelationError, match="nonfinite"):
        loads_relation_json("Infinity")
    with pytest.raises(ProgramRelationError, match="floats are rejected"):
        loads_relation_json('{"score":1.5}')


def test_similarity_is_never_a_semantic_or_authoritative_relation() -> None:
    scope = _scope()
    for kind in (
        "similarity",
        "similar",
        "knn",
        "nearest",
        "embedding_neighbor",
        "neural_similarity",
        "cosine",
    ):
        with pytest.raises(ProgramRelationError, match="not a semantic relation"):
            ProgramRelationClaim.from_scope(
                scope,
                relation_kind=kind,
                left_cid=_cid("left"),
                right_cid=_cid("right"),
            )
    with pytest.raises(ProgramRelationError, match="never an authoritative"):
        RelationValidationReceipt(
            relation_claim_cid=_cid("claim"),
            verdict=RelationValidationVerdict.UNKNOWN,
            authority_status=RelationAuthorityStatus.CANDIDATE,
            contradiction_disposition=ContradictionDisposition.NOT_APPLICABLE,
            similarity_authoritative=True,
        )


def test_scoped_families_do_not_collapse_across_scope_or_environment() -> None:
    left = _scope(scope_kind="module", subject_cids=[_cid("mod.a")])
    right = _scope(scope_kind="theory", subject_cids=[_cid("mod.a")])
    env = _scope(
        scope_kind="module",
        subject_cids=[_cid("mod.a")],
        environment_binding_cid=_cid("env-other"),
    )
    pairs: list[str] = []
    for family_kind in (
        RelationKind.EQUALITY,
        RelationKind.REFINEMENT,
        RelationKind.ENTAILMENT,
        RelationKind.CONTRADICTION,
        RelationKind.COMPATIBILITY,
        RelationKind.LOGICAL_EQUIVALENCE,
    ):
        a = ProgramRelationClaim.from_scope(
            left, relation_kind=family_kind, left_cid=_cid("x"), right_cid=_cid("y")
        )
        b = ProgramRelationClaim.from_scope(
            right, relation_kind=family_kind, left_cid=_cid("x"), right_cid=_cid("y")
        )
        c = ProgramRelationClaim.from_scope(
            env, relation_kind=family_kind, left_cid=_cid("x"), right_cid=_cid("y")
        )
        assert a.relation_family in SCOPED_RELATION_FAMILIES
        assert len({a.relation_claim_cid, b.relation_claim_cid, c.relation_claim_cid}) == 3
        pairs.extend([a.relation_claim_cid, b.relation_claim_cid, c.relation_claim_cid])
    assert len(set(pairs)) == 18


def test_unscoped_and_unbound_claims_are_rejected() -> None:
    scope = _scope()
    with pytest.raises(ProgramRelationError, match="must be a valid CID"):
        ProgramRelationClaim(
            relation_kind="equality",
            left_cid=_cid("left"),
            right_cid=_cid("right"),
            scope_cid="",
            theory_or_policy_cid=scope.theory_or_policy_cid,
            environment_binding_cid=scope.environment_binding_cid,
            authority_status="candidate",
        )
    claim = _claim(scope)
    other = _scope(environment_binding_cid=_cid("env-other"))
    with pytest.raises(ProgramRelationError, match="not bound"):
        claim.bind_scope(other)
    with pytest.raises(ProgramRelationError, match="within the bound scope"):
        ProgramRelationClaim.from_scope(
            scope,
            relation_kind="equality",
            left_cid=_cid("left"),
            right_cid=_cid("right"),
            assumption_cids=[_cid("asm-outside")],
        )


def test_language_unavailability_and_empty_scope_fail_closed() -> None:
    with pytest.raises(ProgramRelationError, match="typed unavailable"):
        _scope(language="javascript")
    with pytest.raises(ProgramRelationError, match="typed unavailable"):
        _scope(language="rust")
    with pytest.raises(ProgramRelationError, match="must not be empty"):
        _scope(subject_cids=[])


def test_contradiction_conflicts_with_positive_families_instead_of_ex_falso() -> None:
    scope = _scope()
    contradiction = _proved(scope, relation_kind=RelationKind.CONTRADICTION)
    equality = _proved(scope, relation_kind=RelationKind.EQUALITY)
    refinement = _proved(scope, relation_kind=RelationKind.REFINEMENT)
    equivalence = _proved(scope, relation_kind=RelationKind.LOGICAL_EQUIVALENCE)
    receipts = validate_relation_set([contradiction, equality, refinement, equivalence])
    by_cid = {item.relation_claim_cid: item for item in receipts}
    for claim in (equality, refinement, equivalence, contradiction):
        receipt = by_cid[claim.relation_claim_cid]
        assert receipt.verdict == RelationValidationVerdict.CONFLICT.value
        assert receipt.contradiction_disposition == ContradictionDisposition.CONFLICT.value
        assert receipt.ex_falso_admission is False
        assert receipt.may_influence_planning is False
        assert may_influence_planning(claim, receipt) is False
    unrelated = _proved(
        scope,
        relation_kind=RelationKind.EQUALITY,
        left_cid=_cid("other-left"),
        right_cid=_cid("other-right"),
    )
    explosion = attempt_ex_falso_admission(contradiction, unrelated)
    assert explosion.verdict == RelationValidationVerdict.ABSTAIN.value
    assert explosion.contradiction_disposition == ContradictionDisposition.ABSTENTION.value
    assert explosion.ex_falso_admission is False
    assert explosion.similarity_authoritative is False
    assert may_influence_planning(unrelated, explosion) is False
    with pytest.raises(ProgramRelationError, match="cannot grant ex falso"):
        RelationValidationReceipt(
            relation_claim_cid=unrelated.relation_claim_cid,
            verdict=RelationValidationVerdict.ADMITTED,
            authority_status=RelationAuthorityStatus.PROVED,
            contradiction_disposition=ContradictionDisposition.NOT_APPLICABLE,
            evidence_cids=unrelated.evidence_cids,
            ex_falso_admission=True,
        )


def test_proved_contradiction_is_admitted_only_as_itself() -> None:
    contradiction = _proved(relation_kind=RelationKind.CONTRADICTION)
    receipt = validate_relation_claim(contradiction)
    assert receipt.verdict == RelationValidationVerdict.ADMITTED.value
    assert receipt.contradiction_disposition == ContradictionDisposition.NOT_APPLICABLE.value
    assert may_influence_planning(contradiction, receipt) is True


def test_refutation_staleness_and_supersession_are_closed() -> None:
    scope = _scope()
    proved = _proved(scope)
    refuted, refutation = invalidate_relation(
        proved,
        RelationInvalidationKind.EVIDENCE_REFUTED,
        [_cid("countermodel")],
    )
    assert refuted.authority_status == RelationAuthorityStatus.REFUTED.value
    assert refutation.resulting_status == "refuted"
    assert refutation.invalidation_kind == "evidence_refuted"
    assert proved.relation_claim_cid != refuted.relation_claim_cid
    stale, stale_record = invalidate_relation(
        proved,
        RelationInvalidationKind.SCOPE_CHANGED,
        [_cid("new-scope")],
    )
    assert stale.authority_status == "stale"
    assert stale_record.successor_claim_cid == stale.relation_claim_cid
    replacement = _proved(scope, evidence_cids=[_cid("proof-2")])
    superseded, supersession = invalidate_relation(
        proved,
        RelationInvalidationKind.SUPERSEDED,
        [_cid("successor")],
        successor_claim_cid=replacement.relation_claim_cid,
    )
    assert superseded.authority_status == "superseded"
    assert superseded.superseded_by_cid == replacement.relation_claim_cid
    assert supersession.successor_claim_cid == replacement.relation_claim_cid
    receipts = [
        validate_relation_claim(refuted),
        validate_relation_claim(stale),
        validate_relation_claim(superseded),
    ]
    assert [item.verdict for item in receipts] == ["refuted", "stale", "superseded"]
    for item in receipts:
        assert item.may_influence_planning is False


def test_scope_assumption_and_environment_invalidation() -> None:
    scope = _scope()
    claim = _proved(scope)
    other_scope = _scope(scope_kind="theory")
    scope_hit = invalidate_by_scope(claim, other_scope)
    assert scope_hit is not None
    stale_scope, scope_record = scope_hit
    assert stale_scope.authority_status == "stale"
    assert scope_record.invalidation_kind == "scope_changed"
    assert invalidate_by_scope(claim, scope) is None

    assumption_hit = invalidate_by_assumption(claim, [_cid("asm-a"), _cid("unrelated")])
    assert assumption_hit is not None
    stale_assumption, assumption_record = assumption_hit
    assert stale_assumption.authority_status == "stale"
    assert assumption_record.invalidation_kind == "assumption_invalidated"
    assert list(assumption_record.invalidator_cids) == [_cid("asm-a")]
    assert invalidate_by_assumption(claim, [_cid("unrelated")]) is None

    env_hit = invalidate_by_environment(claim, _cid("env-v2"))
    assert env_hit is not None
    stale_env, env_record = env_hit
    assert stale_env.authority_status == "stale"
    assert env_record.invalidation_kind == "environment_changed"
    assert invalidate_by_environment(claim, scope.environment_binding_cid) is None

    receipt = validate_relation_claim(
        claim,
        current_scope_cid=other_scope.scope_cid,
        current_environment_binding_cid=_cid("env-v2"),
        invalidated_assumption_cids=[_cid("asm-b")],
    )
    assert receipt.verdict == RelationValidationVerdict.STALE.value
    assert receipt.may_influence_planning is False


def test_authority_transitions_and_evidence_rules_are_closed() -> None:
    claim = _claim()
    asserted = promote_relation(claim, "asserted")
    validated = promote_relation(asserted, "validated", evidence_cids=[_cid("obs-1")])
    proved = promote_relation(validated, "proved", evidence_cids=[_cid("proof-1")])
    assert [item.authority_status for item in (claim, asserted, validated, proved)] == [
        "candidate",
        "asserted",
        "validated",
        "proved",
    ]
    with pytest.raises(ProgramRelationError, match="cannot promote"):
        promote_relation(claim, "proved", evidence_cids=[_cid("proof-1")])
    with pytest.raises(ProgramRelationError, match="cannot promote"):
        promote_relation(proved, "candidate")
    with pytest.raises(ProgramRelationError, match="require evidence_cids"):
        _claim(authority_status="proved")
    with pytest.raises(ProgramRelationError, match="require invalidator_cids"):
        _claim(authority_status="stale")
    with pytest.raises(ProgramRelationError, match="require superseded_by_cid"):
        _claim(authority_status="superseded", invalidator_cids=[_cid("x")])
    with pytest.raises(ProgramRelationError, match="cannot carry invalidators"):
        _proved(invalidator_cids=[_cid("x")])


def test_candidate_relations_are_not_planning_authority() -> None:
    claim = _claim()
    receipt = validate_relation_claim(claim)
    assert receipt.verdict == RelationValidationVerdict.UNKNOWN.value
    assert receipt.may_influence_planning is False
    assert may_influence_planning(claim, receipt) is False
    proved = _proved()
    admitted = validate_relation_claim(proved)
    assert admitted.verdict == "admitted"
    assert may_influence_planning(proved, admitted) is True


def test_symmetric_contradiction_conflicts_regardless_of_operand_order() -> None:
    scope = _scope()
    forward = _proved(
        scope,
        relation_kind="contradiction",
        left_cid=_cid("a"),
        right_cid=_cid("b"),
    )
    reverse_eq = _proved(
        scope,
        relation_kind="equality",
        left_cid=_cid("b"),
        right_cid=_cid("a"),
    )
    pairs = detect_conflicts([forward, reverse_eq])
    assert pairs == (
        tuple(sorted((forward.relation_claim_cid, reverse_eq.relation_claim_cid))),
    )


def test_payload_schema_validates_closed_records_and_rejects_unknowns() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    payloads = _sample_payloads()
    for payload in payloads:
        validator.validate(payload)
    loaded = load_payload_schema()
    assert loaded["$id"].endswith("program-relation.payload.schema.json")
    extra = dict(payloads[1])
    extra["similarity"] = 0.99
    assert list(validator.iter_errors(extra))
    bad_kind = dict(payloads[1])
    bad_kind["relation_kind"] = "similarity"
    assert list(validator.iter_errors(bad_kind))
    bad_version = dict(payloads[1])
    bad_version["schema"] = SCOPED_PROGRAM_RELATION_SCHEMA.replace("@1", "@99")
    assert list(validator.iter_errors(bad_version))
    assert list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "scoped-program-relation@1" in text
    assert "relation-validation-receipt@1" in text
    assert "additionalProperties" in text
    assert "similarity" in text
    assert "ex_falso_admission" in text


def test_json_text_round_trip_uses_closed_decoder() -> None:
    payload = _claim().to_dict()
    encoded = canonical_dag_json_bytes(payload).decode("utf-8")
    decoded = loads_relation_json(encoded)
    assert ProgramRelationClaim.from_dict(decoded).to_dict() == payload
    duplicate = encoded[:-1] + ',"relation_kind":"similarity"}'
    with pytest.raises(ProgramRelationError, match="duplicate JSON key"):
        loads_relation_json(duplicate)
