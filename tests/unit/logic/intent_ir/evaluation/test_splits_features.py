from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.formalization.features import (
    FormalizationFeatures,
)
from ipfs_datasets_py.logic.formalization.samples import (
    FormalizationValidationError,
)
from ipfs_datasets_py.logic.intent_ir.evaluation.splits import (
    HELD_OUT_DOMAIN_PARTITION,
    HELD_OUT_TIME_REVISION_PARTITION,
    TEST_PARTITION,
    TRAIN_PARTITION,
    IntentRetrievalFenceError,
    IntentSplitConfig,
    IntentSplitExample,
    IntentSplitLeakageError,
    IntentSplitManifest,
    build_intent_splits,
    require_leakage_safe_splits,
    require_retrieval_partition_fence,
    validate_intent_splits,
    validate_retrieval_partition_fence,
)
from ipfs_datasets_py.logic.intent_ir.formalize.features import (
    extract_intent_features,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    ReviewStatus,
    SourceRef,
    StatementKind,
)


SECRET = "RAW SECRET source body must never survive"


def _document(**changes: object) -> IntentIRDocument:
    source = SourceRef(
        ref_id="source:1",
        source_uri="https://github.com/example/project/blob/main/SKILL.md",
        source_id="primary:example",
        source_revision="revision-1",
        content_sha256="a" * 64,
        container_uri="hf://datasets/example/skills@revision-1/pilot.sqlite",
        container_sha256="b" * 64,
        license_expression="MIT",
        review_status=ReviewStatus.HUMAN_REVIEWED,
    )
    statements = (
        IntentStatement(
            statement_id="statement:goal",
            kind=StatementKind.GOAL,
            modality=IntentModality.INTENDED,
            normalized_text=SECRET,
            predicate="build",
            arguments=("artifact",),
            source_ref_ids=(source.ref_id,),
        ),
        IntentStatement(
            statement_id="statement:verify",
            kind=StatementKind.VERIFICATION,
            modality=IntentModality.REQUIRED,
            normalized_text="Confirm the artifact exists.",
            source_ref_ids=(source.ref_id,),
        ),
    )
    action = IntentAction(
        action_id="action:build",
        actor="agent",
        verb="build",
        object_refs=("artifact",),
        source_ref_ids=(source.ref_id,),
        verification_ids=("statement:verify",),
    )
    values: dict[str, object] = {
        "document_id": "intent:example",
        "title": SECRET,
        "intent_kind": IntentKind.PROCEDURE,
        "sources": (source,),
        "statements": statements,
        "actions": (action,),
        "control_edges": (
            IntentControlEdge(
                edge_id="control:retry",
                source_action_id=action.action_id,
                target_action_id=action.action_id,
                kind=ControlEdgeKind.RETRY,
                source_ref_ids=(source.ref_id,),
            ),
        ),
        "entry_action_ids": (action.action_id,),
        "terminal_action_ids": (action.action_id,),
        "tags": ("fixture",),
    }
    values.update(changes)
    return IntentIRDocument(**values)  # type: ignore[arg-type]


def _record(sample_id: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "sample_id": sample_id,
        "domain": "security",
        "primary_source_id": f"primary-{sample_id}",
        "repository_id": f"repo-{sample_id}",
        "source_document_id": f"doc-{sample_id}",
        "source_revision": "revision-1",
        "content_sha256": (sample_id.encode().hex() + ("0" * 64))[:64],
        "text": f"Unique procedure text for {sample_id}",
        "observed_date": "2025-01-01",
        "graph_snapshot_id": "graph:snapshot-1",
        "embedding_snapshot_id": "embedding:snapshot-1",
    }
    value.update(changes)
    return value


def test_intent_features_are_numeric_source_free_and_ignore_output_state() -> None:
    features = extract_intent_features(
        _document(),
        context_snapshot_ids=("graph:snapshot-1", "embedding:snapshot-1"),
    )

    payload = features.to_json()
    assert SECRET not in payload
    assert "github.com" not in payload
    assert "human_reviewed" not in payload
    assert "revision-1" not in payload
    assert all(isinstance(item, float) for item in features.model_input)
    assert features.feature_map["statement.kind.verification.count"] == 1.0
    assert tuple(features.feature_map) == tuple(sorted(features.feature_map))

    # Declaration identity changes when source-bearing semantics change, while
    # the advisor's actual numeric input remains source-free and structural.
    changed = _document(
        title="Another private title",
        statements=(
            replace(
                _document().statements[0],
                normalized_text="Completely different private wording",
            ),
            _document().statements[1],
        ),
    )
    changed_features = extract_intent_features(changed)
    assert changed_features.model_input == features.model_input
    assert changed_features.declaration_digest != features.declaration_digest


@pytest.mark.parametrize(
    "name",
    (
        "training.split.label",
        "proof.result",
        "raw.source.body",
        "retrieval.neighbor.count",
        "graph.node.count",
    ),
)
def test_generic_feature_contract_rejects_leakage_prone_names(name: str) -> None:
    with pytest.raises(FormalizationValidationError, match="leakage"):
        FormalizationFeatures.from_values(
            sample_id="sample:1",
            domain="intent",
            declaration_digest="sha256:" + ("a" * 64),
            features={name: 1},
            extractor_id="test-extractor",
            extractor_version="1",
        )


def test_source_variants_repositories_generation_families_and_duplicates_group() -> None:
    samples = [
        _record("source-v1", primary_source_id="primary-shared"),
        _record(
            "source-v2",
            primary_source_id="primary-shared",
            source_revision="revision-2",
        ),
        _record("repo-a", repository_id="repo-shared"),
        _record("repo-b", repository_id="repo-shared"),
        _record("generated-a", generation_family_id="prompt-model-family"),
        _record("generated-b", generation_family_id="prompt-model-family"),
        _record(
            "duplicate-a",
            text="Publish the public report within thirty days.",
        ),
        _record(
            "duplicate-b",
            text="PUBLISH  the public report within thirty days!",
        ),
    ]

    first = build_intent_splits(samples, IntentSplitConfig(seed="grouping"))
    second = build_intent_splits(
        list(reversed(samples)), IntentSplitConfig(seed="grouping")
    )

    assert first.digest == second.digest
    assert first.assignments["source-v1"] == first.assignments["source-v2"]
    assert first.assignments["repo-a"] == first.assignments["repo-b"]
    assert first.assignments["generated-a"] == first.assignments["generated-b"]
    assert first.assignments["duplicate-a"] == first.assignments["duplicate-b"]
    assert first.guard_result().passed is True


def test_explicit_domain_and_time_revision_holdouts_apply_to_whole_groups() -> None:
    manifest = build_intent_splits(
        [
            _record(
                "domain-a",
                domain="finance",
                primary_source_id="domain-family",
            ),
            _record(
                "domain-variant",
                domain="general",
                primary_source_id="domain-family",
            ),
            _record(
                "future-a",
                observed_date="2027-02-01",
                primary_source_id="future-family",
            ),
            _record(
                "future-old-variant",
                observed_date="2024-01-01",
                primary_source_id="future-family",
            ),
            _record("revision-a", source_revision="revision-held"),
        ],
        IntentSplitConfig(
            seed="holdouts",
            held_out_domains=("finance",),
            temporal_holdout_after="2026-01-01",
            held_out_revisions=("revision-held",),
        ),
    )

    assert manifest.assignments["domain-a"] == HELD_OUT_DOMAIN_PARTITION
    assert manifest.assignments["domain-variant"] == HELD_OUT_DOMAIN_PARTITION
    assert manifest.assignments["future-a"] == HELD_OUT_TIME_REVISION_PARTITION
    assert (
        manifest.assignments["future-old-variant"]
        == HELD_OUT_TIME_REVISION_PARTITION
    )
    assert manifest.assignments["revision-a"] == HELD_OUT_TIME_REVISION_PARTITION


def test_manifest_is_source_free_and_detects_adversarial_tampering() -> None:
    samples = [
        _record(
            "copy-a",
            primary_source_id="shared-source",
            content_sha256="c" * 64,
            text=SECRET,
        ),
        _record(
            "copy-b",
            primary_source_id="shared-source",
            content_sha256="c" * 64,
            text=SECRET.lower() + "!",
        ),
    ]
    manifest = build_intent_splits(samples, IntentSplitConfig(seed="tamper"))
    serialized = manifest.to_json()

    assert SECRET not in serialized
    assert SECRET.lower() not in serialized
    payload = manifest.to_dict(include_digest=False)
    payload["assignments"]["copy-a"] = TRAIN_PARTITION
    payload["assignments"]["copy-b"] = TEST_PARTITION

    result = validate_intent_splits(payload)
    assert result.passed is False
    assert {item.kind for item in result.violations} >= {
        "content",
        "near_duplicate",
        "primary_source",
    }
    with pytest.raises(IntentSplitLeakageError):
        require_leakage_safe_splits(payload)


def test_manifest_detects_duplicate_membership_in_partition_projection() -> None:
    examples = (
        IntentSplitExample.from_sample(_record("one")),
        IntentSplitExample.from_sample(_record("two")),
    )
    payload = {
        "config_digest": "sha256:" + ("a" * 64),
        "examples": [item.to_dict() for item in examples],
        "partitions": [
            "train",
            "validation",
            "test",
            "held_out_domain",
            "held_out_time_revision",
        ],
        "samples_by_partition": {
            "train": ["one", "two"],
            "test": ["one"],
        },
        "schema_version": "intent-split-manifest/v1",
    }
    result = validate_intent_splits(payload)
    assert result.passed is False
    assert any(item.kind == "assignment" for item in result.violations)


def test_retrieval_fence_rejects_cross_partition_unknown_and_snapshot_candidates() -> None:
    examples = tuple(
        IntentSplitExample.from_sample(_record(sample_id))
        for sample_id in ("query", "same", "cross", "stale")
    )
    examples = tuple(
        replace(item, graph_snapshot_id="graph:stale")
        if item.sample_id == "stale"
        else item
        for item in examples
    )
    manifest = IntentSplitManifest(
        examples=examples,
        assignments={
            "query": TEST_PARTITION,
            "same": TEST_PARTITION,
            "cross": TRAIN_PARTITION,
            "stale": TEST_PARTITION,
        },
        config_digest="sha256:" + ("a" * 64),
    )

    allowed = require_retrieval_partition_fence(
        manifest, "query", ("same",)
    )
    assert allowed.partition == TEST_PARTITION
    assert allowed.graph_snapshot_id == "graph:snapshot-1"

    result = validate_retrieval_partition_fence(
        manifest, "query", ("cross", "stale", "missing")
    )
    assert result.passed is False
    assert {item.reason for item in result.violations} == {
        "candidate_not_in_manifest",
        "cross_partition",
        "graph_snapshot_mismatch",
    }
    with pytest.raises(IntentRetrievalFenceError):
        require_retrieval_partition_fence(manifest, "query", ("cross",))
    current_snapshot = validate_retrieval_partition_fence(
        manifest,
        "query",
        ("same",),
        graph_snapshot_id="graph:other",
    )
    assert {item.reason for item in current_snapshot.violations} >= {
        "query_graph_snapshot_mismatch",
        "graph_snapshot_mismatch",
    }


def test_split_contracts_are_immutable_and_round_trip_canonically() -> None:
    manifest = build_intent_splits([_record("one"), _record("two")])
    decoded = IntentSplitManifest.from_dict(
        json.loads(manifest.to_json())
    )

    assert decoded.digest == manifest.digest
    with pytest.raises(TypeError):
        decoded.assignments["one"] = TEST_PARTITION  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        decoded.config_digest = "changed"  # type: ignore[misc]
