"""Contract vectors for program-world identity and canonicalization profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    PROFILE_VERSION,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_obj,
    cid_for_structured,
    cid_vectors_document,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    SEMANTIC_STATE_ROOT_SCHEMA,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
    ABSTRACT_EXECUTION_STATE_IDENTITY_SCHEMA,
    CANONICAL_PROGRAM_GRAPH_IDENTITY_SCHEMA,
    PROGRAM_WORLD_CANONICALIZATION_PROFILE_INTERFACE,
    PROGRAM_WORLD_CANONICALIZATION_PROFILE_SCHEMA,
    PROJECTION_IDENTITY_INTERFACE,
    PROJECTION_IDENTITY_SCHEMA,
    RAW_EXECUTION_STATE_IDENTITY_SCHEMA,
    SEMANTIC_OBJECT_ENVELOPE_INTERFACE,
    SEMANTIC_OBJECT_ENVELOPE_SCHEMA,
    AbstractExecutionStateIdentity,
    CanonicalProgramGraphIdentity,
    ExecutionTraceIdentity,
    ObservationStatus,
    ProgramEventIdentity,
    ProgramGraphDeltaIdentity,
    ProgramGraphSnapshotIdentity,
    ProgramIdentityError,
    ProgramLanguage,
    ProjectionIdentity,
    ProjectionIndexManifestIdentity,
    ProjectionKind,
    RawExecutionStateIdentity,
    RelationClaimIdentity,
    RelationKind,
    SemanticObjectEnvelope,
    SemanticObjectKind,
    SemanticWorldRootIdentity,
    StackFrameIdentity,
    StateAbstractionProfileIdentity,
    TransitionIdentity,
    TransitionKind,
    canonical_identity_bytes,
    canonicalize_identity_value,
    decode_identity_record,
    identity_cid_for,
    load_payload_schema,
    loads_identity_json,
    program_world_profile,
    projection_from_bindings,
    semantic_object_from_declaration,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "program-identity.payload.schema.json"
)

EXISTING_V1_SOURCE_HELLO_CID = (
    "bafkreibm6jg3ux5qumhcn2b3flc3tyu6dmlb4xa7u5bf44yegnrjhc4yeq"
)
EXISTING_V1_STRUCTURED_AB_CID = (
    "baguqeera2nrgvqykq7tppjscqiz3hructglwqzp2kueoijt4kqk4o2xxu5za"
)
EXISTING_V1_STRUCTURED_AB_BYTES = b'{"a":2,"b":1}'


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _source() -> str:
    return cid_for_bytes(b"def answer():\n    return 1\n")


def _envelope(**overrides: Any) -> SemanticObjectEnvelope:
    fields: dict[str, Any] = {
        "kind": SemanticObjectKind.SYMBOL,
        "language": ProgramLanguage.PYTHON,
        "repository_id": "repo:example",
        "logical_name": "pkg.mod.answer",
        "declaration_cid": _source(),
        "source_cid": _source(),
        "environment_binding_cid": None,
        "metadata": {},
    }
    fields.update(overrides)
    return SemanticObjectEnvelope(**fields)


def _projection(*, subject: str | None = None, **overrides: Any) -> ProjectionIdentity:
    fields: dict[str, Any] = {
        "subject_cid": subject or _envelope().semantic_object_cid,
        "subject_kind": "semantic_object",
        "projection_kind": ProjectionKind.EMBEDDING,
        "model_cid": _cid("model-a"),
        "tokenizer_cid": _cid("tokenizer-a"),
        "preprocessing_profile_cid": _cid("preproc-a"),
        "normalization_profile_cid": _cid("norm-a"),
        "dimension": 8,
        "metric": "cosine",
        "dtype": "float32",
        "byte_order": "little",
        "quantization_profile_cid": None,
        "vector_cid": _cid("vector-a"),
        "privacy_class": "internal",
        "availability_policy": "available",
        "authoritative": False,
    }
    fields.update(overrides)
    return ProjectionIdentity(**fields)


def _raw(**overrides: Any) -> RawExecutionStateIdentity:
    fields: dict[str, Any] = {
        "language": "python",
        "capture_profile_cid": _cid("capture-v1"),
        "observed_state": {"locals": {"x": 1}},
        "stack_frame_cids": (),
        "unavailable_dimensions": (),
        "observation_status": ObservationStatus.OBSERVED,
    }
    fields.update(overrides)
    return RawExecutionStateIdentity(**fields)


def _abstraction(**overrides: Any) -> StateAbstractionProfileIdentity:
    fields: dict[str, Any] = {
        "language": "python",
        "profile_name": "interval-v1",
        "dimensions": ["locals", "heap"],
        "unavailable_dimensions": ("native_stack",),
        "soundness_claim": "over_approximation",
    }
    fields.update(overrides)
    return StateAbstractionProfileIdentity(**fields)


def _sample_payloads() -> list[dict[str, Any]]:
    envelope = _envelope()
    graph = CanonicalProgramGraphIdentity(
        language="python",
        graph_kind="static_logical",
        node_cids=[_cid("n2"), _cid("n1")],
        edge_cids=[_cid("e1")],
        environment_binding_set_cid=_cid("bindings"),
        unavailable_dimensions=["reflection"],
    )
    snapshot = ProgramGraphSnapshotIdentity(
        canonical_program_graph_cid=graph.canonical_program_graph_cid,
        node_cids=graph.node_cids,
        edge_cids=graph.edge_cids,
        environment_binding_set_cid=_cid("bindings"),
        sealed_binding_cid=_cid("sealed"),
    )
    delta = ProgramGraphDeltaIdentity(
        previous_snapshot_cid=snapshot.program_graph_snapshot_cid,
        added_node_cids=[_cid("n3")],
        retained_subroot_cids=[_cid("n1")],
    )
    frame = StackFrameIdentity(
        ordinal=0,
        language="python",
        code_cid=_source(),
        environment_binding_cid=_cid("env"),
        state_summary={"locals": {"x": 1}},
    )
    raw = _raw(stack_frame_cids=[frame.stack_frame_cid])
    profile = _abstraction()
    abstract = AbstractExecutionStateIdentity(
        language="python",
        raw_execution_state_cid=raw.raw_execution_state_cid,
        abstraction_profile_cid=profile.abstraction_profile_cid,
        abstract_state={"locals": {"x": "int"}},
        unavailable_dimensions=["native_stack"],
        observation_status="observed",
    )
    event = ProgramEventIdentity(
        event_kind="call",
        observation_status="observed",
        subject_cid=envelope.semantic_object_cid,
        payload={"callee": "pkg.mod.answer"},
        predecessor_event_cid=None,
    )
    event_again = ProgramEventIdentity(
        event_kind="return",
        observation_status="observed",
        subject_cid=envelope.semantic_object_cid,
        payload={"value": 1},
        predecessor_event_cid=event.program_event_cid,
    )
    trace = ExecutionTraceIdentity(
        event_cids=[event.program_event_cid, event_again.program_event_cid, event.program_event_cid],
        raw_execution_state_cids=[raw.raw_execution_state_cid, raw.raw_execution_state_cid],
    )
    projection = _projection(subject=envelope.semantic_object_cid)
    manifest = ProjectionIndexManifestIdentity(
        projection_kind="embedding",
        model_cid=projection.model_cid,
        tokenizer_cid=projection.tokenizer_cid,
        preprocessing_profile_cid=projection.preprocessing_profile_cid,
        dimension=8,
        metric="cosine",
        dtype="float32",
        byte_order="little",
        source_cid=envelope.semantic_object_cid,
        schema_ids=["program-identity@1"],
    )
    relation = RelationClaimIdentity(
        relation_kind=RelationKind.EQUALITY,
        left_cid=envelope.semantic_object_cid,
        right_cid=_cid("other-object"),
        scope_cid=_cid("scope"),
        theory_or_policy_cid=_cid("policy"),
        environment_binding_cid=_cid("env"),
        authority_status="candidate",
        assumption_cids=[_cid("a2"), _cid("a1")],
        evidence_cids=[_cid("ev1")],
        invalidator_cids=(),
    )
    query = TransitionIdentity(
        transition_kind=TransitionKind.QUERY,
        subject_cid=raw.raw_execution_state_cid,
        evidence_cids=[_cid("ev")],
        environment_binding_cid=_cid("env"),
        policy_cid=_cid("policy"),
    )
    prediction = TransitionIdentity(
        transition_kind=TransitionKind.PREDICTION,
        subject_cid=raw.raw_execution_state_cid,
        evidence_cids=[_cid("ev")],
        model_profile_cid=_cid("model-profile"),
        proposal_only=True,
    )
    world = SemanticWorldRootIdentity(
        domain_state_cid=_cid("domain"),
        canonical_program_graph_cid=graph.canonical_program_graph_cid,
        program_graph_snapshot_cid=snapshot.program_graph_snapshot_cid,
        semantic_object_index_cid=_cid("objects"),
        environment_binding_set_cid=_cid("bindings"),
        policy_cid=_cid("policy"),
        analysis_limitation_index_cid=_cid("limits"),
    )
    return [
        program_world_profile().to_dict(),
        envelope.to_dict(),
        graph.to_dict(),
        snapshot.to_dict(),
        delta.to_dict(),
        raw.to_dict(),
        profile.to_dict(),
        abstract.to_dict(),
        frame.to_dict(),
        event.to_dict(),
        trace.to_dict(),
        projection.to_dict(),
        manifest.to_dict(),
        relation.to_dict(),
        query.to_dict(),
        prediction.to_dict(),
        world.to_dict(),
    ]


def test_public_interfaces_are_versioned() -> None:
    profile = program_world_profile()
    assert SEMANTIC_OBJECT_ENVELOPE_INTERFACE == "SemanticObjectEnvelope@1"
    assert PROGRAM_WORLD_CANONICALIZATION_PROFILE_INTERFACE == (
        "ProgramWorldCanonicalizationProfile@1"
    )
    assert PROJECTION_IDENTITY_INTERFACE == "ProjectionIdentity@1"
    assert profile.SCHEMA == PROGRAM_WORLD_CANONICALIZATION_PROFILE_SCHEMA
    assert SemanticObjectEnvelope.SCHEMA == SEMANTIC_OBJECT_ENVELOPE_SCHEMA
    assert ProjectionIdentity.SCHEMA == PROJECTION_IDENTITY_SCHEMA
    assert profile.cid_profile_id == PROFILE_ID == "software-contract-cid-profile-v1"
    assert profile.cid_profile_version == PROFILE_VERSION
    assert profile.canonical_json_profile == "ir-canonical-json-v1"
    assert profile.admitted_languages == ("python",)
    assert profile.semantic_object_identity_may_derive_from_embedding_score is False
    assert profile.existing_v1_payload_may_change is False
    assert profile.claimed_cid_must_rehash is True


def test_existing_v1_content_vectors_remain_byte_identical() -> None:
    assert cid_for_bytes(b"hello") == EXISTING_V1_SOURCE_HELLO_CID
    assert canonical_dag_json_bytes({"b": 1, "a": 2}) == EXISTING_V1_STRUCTURED_AB_BYTES
    assert cid_for_obj({"a": 2, "b": 1}) == EXISTING_V1_STRUCTURED_AB_CID
    assert cid_for_obj({"b": 1, "a": 2}) == EXISTING_V1_STRUCTURED_AB_CID
    live = cid_vectors_document()
    assert live["schema"] == "ipfs-datasets.software-contract-cid-vectors.v1"
    assert live["profile"]["profile_id"] == "software-contract-cid-profile-v1"
    by_id = {item["id"]: item for item in live["vectors"]}
    assert by_id["source.hello"]["expected_cid"] == EXISTING_V1_SOURCE_HELLO_CID
    assert by_id["structured.simple_map"]["expected_cid"] == EXISTING_V1_STRUCTURED_AB_CID
    assert by_id["structured.key_order_independent"]["expected_cid"] == (
        EXISTING_V1_STRUCTURED_AB_CID
    )
    assert by_id["structured.simple_map"]["canonical_utf8"] == '{"a":2,"b":1}'


def test_existing_semantic_state_root_v1_encoder_is_unchanged() -> None:
    index = SortedPairIndex(pairs=[("k", _cid("block"))])
    producer = SemanticStateProducer(
        repository_state_cid=_cid("state"),
        repository_snapshot_cid=_cid("snapshot"),
        git_commit_oid_or_null=None,
        git_tree_oid_or_null=None,
        source_manifest_cid=_cid("manifest"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )
    root = SemanticStateRoot(
        repository_id="repo:example",
        producer=producer,
        symbol_fact_index_cid=index.index_cid,
        artifact_fact_index_cid=index.index_cid,
        semantic_link_index_cid=index.index_cid,
        symbol_node_index_cid=index.index_cid,
        capsule_index_cid=index.index_cid,
        environment_binding_set_cid=index.index_cid,
        analysis_limitation_index_cid=index.index_cid,
    )
    payload = root.identity_payload()
    assert payload["schema"] == SEMANTIC_STATE_ROOT_SCHEMA
    assert root.root_cid == cid_for_structured(payload)
    assert "timestamp" not in payload
    assert "model" not in payload
    assert canonical_dag_json_bytes(payload) == canonical_identity_bytes(payload)


def test_profile_and_envelopes_round_trip_and_rehash() -> None:
    for payload in _sample_payloads():
        record = decode_identity_record(payload)
        assert record.to_dict() == payload
        identity = record.identity_payload()
        claimed = payload[record.CID_FIELD]
        assert decode_and_recompute_structured(claimed, identity) == claimed
        again = json.loads(json.dumps(payload, sort_keys=True))
        assert decode_identity_record(again).to_dict() == payload


def test_golden_canonical_bytes_and_cids_are_stable() -> None:
    envelope = _envelope()
    expected_payload = {
        "schema": SEMANTIC_OBJECT_ENVELOPE_SCHEMA,
        "kind": "symbol",
        "language": "python",
        "repository_id": "repo:example",
        "logical_name": "pkg.mod.answer",
        "declaration_cid": _source(),
        "source_cid": _source(),
        "environment_binding_cid": None,
        "metadata": {},
    }
    assert envelope.identity_payload() == expected_payload
    assert envelope.canonical_bytes() == canonical_dag_json_bytes(expected_payload)
    assert envelope.semantic_object_cid == cid_for_structured(expected_payload)
    assert envelope.semantic_object_cid == identity_cid_for(expected_payload)
    profile = program_world_profile()
    assert profile.profile_cid == cid_for_structured(profile.identity_payload())
    assert program_world_profile().profile_cid == profile.profile_cid


def test_unknown_fields_and_versions_are_rejected() -> None:
    payload = _envelope().to_dict()
    with pytest.raises(ProgramIdentityError, match="unknown fields"):
        SemanticObjectEnvelope.from_dict({**payload, "timestamp": "2026-01-01"})
    with pytest.raises(ProgramIdentityError, match="unknown fields"):
        SemanticObjectEnvelope.from_dict({**payload, "embedding": [0, 1]})
    with pytest.raises(ProgramIdentityError, match="schema version"):
        SemanticObjectEnvelope.from_dict(
            {**payload, "schema": SEMANTIC_OBJECT_ENVELOPE_SCHEMA.replace("@1", "@99")}
        )
    forged = dict(payload)
    forged["semantic_object_cid"] = _cid("forged")
    with pytest.raises(ProgramIdentityError, match="does not verify"):
        SemanticObjectEnvelope.from_dict(forged)
    with pytest.raises(ProgramIdentityError, match="unsupported identity schema"):
        decode_identity_record({"schema": "not-a-payload", "x": 1})


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected() -> None:
    with pytest.raises(ProgramIdentityError, match="duplicate JSON key"):
        loads_identity_json('{"a":1,"a":2}')
    with pytest.raises(ProgramIdentityError, match="nonfinite"):
        loads_identity_json("NaN")
    with pytest.raises(ProgramIdentityError, match="nonfinite"):
        loads_identity_json("Infinity")
    with pytest.raises(ProgramIdentityError, match="floats are rejected"):
        loads_identity_json('{"score":1.5}')
    with pytest.raises(ProgramIdentityError, match="strict DAG-JSON"):
        SemanticObjectEnvelope(
            kind="symbol",
            language="python",
            repository_id="repo:example",
            logical_name="pkg.mod.answer",
            declaration_cid=_source(),
            metadata={"ratio": 1.5},  # type: ignore[dict-item]
        )
    with pytest.raises(ProgramIdentityError, match="strict DAG-JSON"):
        canonicalize_identity_value({"x": float("nan")})


def test_unsupported_language_and_private_fields_fail_closed() -> None:
    with pytest.raises(ProgramIdentityError, match="typed unavailable"):
        _envelope(language="javascript")
    with pytest.raises(ProgramIdentityError, match="typed unavailable"):
        _envelope(language="rust")
    with pytest.raises(ProgramIdentityError, match="private fields"):
        _envelope(metadata={"secret": "nope"})
    with pytest.raises(ProgramIdentityError, match="non-semantic fields"):
        _envelope(metadata={"timestamp": "now"})


def test_model_dependent_projection_does_not_change_semantic_object_identity() -> None:
    envelope = _envelope()
    projection_a = _projection(subject=envelope.semantic_object_cid, model_cid=_cid("model-a"))
    projection_b = _projection(
        subject=envelope.semantic_object_cid,
        model_cid=_cid("model-b"),
        tokenizer_cid=_cid("tokenizer-b"),
        preprocessing_profile_cid=_cid("preproc-b"),
        dimension=16,
        metric="euclidean",
        vector_cid=_cid("vector-b"),
    )
    assert projection_a.subject_cid == envelope.semantic_object_cid
    assert projection_b.subject_cid == envelope.semantic_object_cid
    assert projection_a.projection_cid != projection_b.projection_cid
    observed = semantic_object_from_declaration(
        {
            "kind": "symbol",
            "language": "python",
            "repository_id": "repo:example",
            "logical_name": "pkg.mod.answer",
            "declaration_cid": _source(),
            "source_cid": _source(),
            "embedding": [0.1, 0.2],
            "score": 0.99,
            "model_cid": _cid("model-a"),
            "tokenizer_cid": _cid("tokenizer-a"),
            "vector_cid": _cid("vector-a"),
            "timestamp": "2026-08-29T00:00:00Z",
            "wall_clock": 123,
            "observed_at": "now",
        }
    )
    assert observed.semantic_object_cid == envelope.semantic_object_cid
    assert "embedding" not in observed.identity_payload()
    assert "model_cid" not in observed.identity_payload()


def test_irrelevant_observations_do_not_perturb_semantic_or_state_identity() -> None:
    left = semantic_object_from_declaration(
        {
            "kind": "symbol",
            "language": "python",
            "repository_id": "repo:example",
            "logical_name": "pkg.mod.answer",
            "declaration": {"body": "def answer():\n    return 1\n"},
            "pid": 4321,
            "hostname": "worker-9",
            "request_id": "abc",
            "attempt": 7,
        }
    )
    right = semantic_object_from_declaration(
        {
            "kind": "symbol",
            "language": "python",
            "repository_id": "repo:example",
            "logical_name": "pkg.mod.answer",
            "declaration": {
                "body": "def answer():\n    return 1\n",
                "timestamp": "later",
                "score": 0.1,
            },
            "timestamp": "2026-01-01T00:00:00Z",
            "lease": "lease-1",
            "generation": 9,
        }
    )
    assert left.semantic_object_cid == right.semantic_object_cid
    raw = _raw()
    with pytest.raises(ProgramIdentityError, match="unknown fields"):
        RawExecutionStateIdentity.from_dict({**raw.to_dict(), "wall_clock": 1})
    with pytest.raises(ProgramIdentityError, match="non-semantic fields"):
        _raw(observed_state={"x": 1, "timestamp": "now"})


def test_projection_changes_change_projection_identity_only() -> None:
    envelope = _envelope()
    base = projection_from_bindings(
        subject_cid=envelope.semantic_object_cid,
        model_cid=_cid("model-a"),
        tokenizer_cid=_cid("tok-a"),
        preprocessing_profile_cid=_cid("pre-a"),
        normalization_profile_cid=_cid("norm-a"),
        dimension=4,
        metric="cosine",
        dtype="float32",
        byte_order="little",
        vector_cid=_cid("vec-a"),
    )
    swapped_model = projection_from_bindings(
        subject_cid=envelope.semantic_object_cid,
        model_cid=_cid("model-b"),
        tokenizer_cid=_cid("tok-a"),
        preprocessing_profile_cid=_cid("pre-a"),
        normalization_profile_cid=_cid("norm-a"),
        dimension=4,
        metric="cosine",
        dtype="float32",
        byte_order="little",
        vector_cid=_cid("vec-a"),
    )
    swapped_preproc = projection_from_bindings(
        subject_cid=envelope.semantic_object_cid,
        model_cid=_cid("model-a"),
        tokenizer_cid=_cid("tok-a"),
        preprocessing_profile_cid=_cid("pre-b"),
        normalization_profile_cid=_cid("norm-a"),
        dimension=4,
        metric="cosine",
        dtype="float32",
        byte_order="little",
        vector_cid=_cid("vec-a"),
    )
    swapped_endian = projection_from_bindings(
        subject_cid=envelope.semantic_object_cid,
        model_cid=_cid("model-a"),
        tokenizer_cid=_cid("tok-a"),
        preprocessing_profile_cid=_cid("pre-a"),
        normalization_profile_cid=_cid("norm-a"),
        dimension=4,
        metric="cosine",
        dtype="float32",
        byte_order="big",
        vector_cid=_cid("vec-a"),
    )
    cids = {
        base.projection_cid,
        swapped_model.projection_cid,
        swapped_preproc.projection_cid,
        swapped_endian.projection_cid,
    }
    assert len(cids) == 4
    assert {base.subject_cid, swapped_model.subject_cid} == {envelope.semantic_object_cid}


def test_projection_rejects_unpinned_unspecified_and_authoritative_flags() -> None:
    envelope = _envelope()
    with pytest.raises(ProgramIdentityError, match="must be a valid CID"):
        _projection(subject=envelope.semantic_object_cid, model_cid="")
    with pytest.raises(ProgramIdentityError, match="unsupported value"):
        _projection(subject=envelope.semantic_object_cid, byte_order="unspecified")
    with pytest.raises(ProgramIdentityError, match="non-authoritative"):
        _projection(subject=envelope.semantic_object_cid, authoritative=True)
    with pytest.raises(ProgramIdentityError, match="integer in 1.."):
        _projection(subject=envelope.semantic_object_cid, dimension=0)


def test_raw_and_abstract_identities_are_distinct_and_profile_bound() -> None:
    raw = _raw()
    profile = _abstraction()
    abstract = AbstractExecutionStateIdentity(
        language="python",
        raw_execution_state_cid=raw.raw_execution_state_cid,
        abstraction_profile_cid=profile.abstraction_profile_cid,
        abstract_state={"locals": {"x": "int"}},
        unavailable_dimensions=["native_stack"],
    )
    other_profile = _abstraction(profile_name="sign-v1", dimensions=["locals"])
    abstract_other = AbstractExecutionStateIdentity(
        language="python",
        raw_execution_state_cid=raw.raw_execution_state_cid,
        abstraction_profile_cid=other_profile.abstraction_profile_cid,
        abstract_state={"locals": {"x": "int"}},
        unavailable_dimensions=["native_stack"],
    )
    assert raw.raw_execution_state_cid != abstract.abstract_execution_state_cid
    assert abstract.raw_execution_state_cid == raw.raw_execution_state_cid
    assert abstract.SCHEMA == ABSTRACT_EXECUTION_STATE_IDENTITY_SCHEMA
    assert raw.SCHEMA == RAW_EXECUTION_STATE_IDENTITY_SCHEMA
    assert "abstraction_profile_cid" not in raw.identity_payload()
    assert abstract.abstract_execution_state_cid != abstract_other.abstract_execution_state_cid
    assert other_profile.abstraction_profile_cid != profile.abstraction_profile_cid


def test_set_like_collections_are_order_independent_and_traces_preserve_repeats() -> None:
    left = CanonicalProgramGraphIdentity(
        language="python",
        graph_kind="static_logical",
        node_cids=[_cid("n2"), _cid("n1")],
        edge_cids=[_cid("e2"), _cid("e1")],
    )
    right = CanonicalProgramGraphIdentity(
        language="python",
        graph_kind="static_logical",
        node_cids=[_cid("n1"), _cid("n2")],
        edge_cids=[_cid("e1"), _cid("e2")],
    )
    assert left.canonical_program_graph_cid == right.canonical_program_graph_cid
    assert left.SCHEMA == CANONICAL_PROGRAM_GRAPH_IDENTITY_SCHEMA
    assert list(left.node_cids) == sorted(left.node_cids)
    event = _cid("event")
    repeated = ExecutionTraceIdentity(event_cids=[event, event])
    collapsed = ExecutionTraceIdentity(event_cids=[event])
    assert repeated.execution_trace_cid != collapsed.execution_trace_cid
    assert list(repeated.event_cids) == [event, event]


def test_relation_identity_rejects_similarity_and_transition_rules_are_closed() -> None:
    with pytest.raises(ProgramIdentityError, match="not a semantic relation"):
        RelationClaimIdentity(
            relation_kind="similarity",
            left_cid=_cid("a"),
            right_cid=_cid("b"),
            scope_cid=_cid("s"),
            theory_or_policy_cid=_cid("p"),
            environment_binding_cid=_cid("e"),
            authority_status="candidate",
        )
    with pytest.raises(ProgramIdentityError, match="proposal-only"):
        TransitionIdentity(
            transition_kind="prediction",
            subject_cid=_cid("s"),
            model_profile_cid=_cid("m"),
            proposal_only=False,
        )
    with pytest.raises(ProgramIdentityError, match="require model_profile_cid"):
        TransitionIdentity(transition_kind="prediction", subject_cid=_cid("s"), proposal_only=True)
    with pytest.raises(ProgramIdentityError, match="cannot be proposal-only"):
        TransitionIdentity(transition_kind="accepted", subject_cid=_cid("s"), proposal_only=True)
    with pytest.raises(ProgramIdentityError, match="require observation_status"):
        TransitionIdentity(transition_kind="observation", subject_cid=_cid("s"))
    with pytest.raises(ProgramIdentityError, match="require policy_cid"):
        TransitionIdentity(transition_kind="admission", subject_cid=_cid("s"))


def test_world_root_excludes_projections_and_verifies_cid() -> None:
    world = SemanticWorldRootIdentity(
        domain_state_cid=_cid("domain"),
        canonical_program_graph_cid=_cid("graph"),
        program_graph_snapshot_cid=_cid("snap"),
        semantic_object_index_cid=_cid("objects"),
        environment_binding_set_cid=_cid("bindings"),
        policy_cid=_cid("policy"),
        analysis_limitation_index_cid=_cid("limits"),
    )
    payload = world.to_dict()
    assert "projection_cid" not in payload
    assert "timestamp" not in payload
    assert world.semantic_world_root_cid == cid_for_structured(world.identity_payload())
    with pytest.raises(ProgramIdentityError, match="excluded fields"):
        SemanticWorldRootIdentity.from_dict({**payload, "timestamp": "now"})


def test_payload_schema_validates_closed_records_and_rejects_unknowns() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    payloads = _sample_payloads()
    for payload in payloads:
        validator.validate(payload)
    loaded = load_payload_schema()
    assert loaded["$id"].endswith("program-identity.payload.schema.json")
    extra = dict(payloads[1])
    extra["embedding"] = [0, 1]
    assert list(validator.iter_errors(extra))
    bad_version = dict(payloads[1])
    bad_version["schema"] = "ipfs-datasets.software-contracts.semantic-object-envelope@99"
    assert list(validator.iter_errors(bad_version))
    assert list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    assert SCHEMA_PATH.is_file()
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "semantic-object-envelope@1" in text
    assert "program-world-canonicalization-profile@1" in text
    assert "additionalProperties" in text
    assert "software-contract-cid-profile-v1" in text


def test_json_text_round_trip_uses_closed_decoder() -> None:
    payload = _envelope().to_dict()
    encoded = canonical_dag_json_bytes(payload).decode("utf-8")
    decoded = loads_identity_json(encoded)
    assert SemanticObjectEnvelope.from_dict(decoded).to_dict() == payload
    duplicate = encoded[:-1] + ',"kind":"artifact"}'
    with pytest.raises(ProgramIdentityError, match="duplicate JSON key"):
        loads_identity_json(duplicate)
