"""CRYPTOIR-G760 lineage-safe partition and retrieval-fence conformance tests."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.partitions import (
    ADVERSARIAL_PARTITION,
    HELD_OUT_PARTITION,
    SOLIDITY_PARTITIONS,
    TEST_PARTITION,
    TRAIN_PARTITION,
    UPSTREAM_SOURCE_SPLIT,
    VALIDATION_PARTITION,
    DuplicateFamily,
    SolidityPartitionConfig,
    SolidityPartitionError,
    SolidityPartitionExample,
    SolidityPartitionLeakageError,
    SolidityPartitionManifest,
    SolidityRetrievalFenceError,
    build_solidity_partitions,
    require_leakage_safe_partitions,
    require_retrieval_partition_fence,
    validate_retrieval_partition_fence,
    validate_solidity_partitions,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.release_policy import (
    SOLIDITY_CPT_DATASET_ID,
    SOLIDITY_CPT_REVISION,
    SOLIDITY_CPT_SPLIT,
)


SECRET = "contract Vault { function secretDrain() public {} }"


def _record(sample_id: str, **changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "sample_id": sample_id,
        "source": "etherscan",
        "address": "0x" + ("1" * 40),
        "path": f"contracts/{sample_id}.sol",
        "text": f"contract {sample_id.replace('-', '_')} {{ uint256 x; }}",
        "graph_snapshot_id": "graph:snapshot-1",
        "embedding_snapshot_id": "embed:snapshot-1",
        "source_snapshot_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    }
    base.update(changes)
    return base


def test_connected_groups_form_before_assignment_for_all_lineage_signals() -> None:
    samples = [
        _record(
            "content-a",
            text="Publish the vault report within thirty days.",
            address="0x" + ("a" * 40),
            path="unique/content-a.sol",
        ),
        _record(
            "content-b",
            text="PUBLISH  the vault report within thirty days!",
            address="0x" + ("b" * 40),
            path="unique/content-b.sol",
        ),
        _record(
            "repo-a",
            repository_id="https://github.com/acme/vault",
            address="0x" + ("c" * 40),
            path="src/A.sol",
            text="contract RepoA { }",
        ),
        _record(
            "repo-b",
            repository_id="https://github.com/acme/vault",
            address="0x" + ("d" * 40),
            path="src/B.sol",
            text="contract RepoB { }",
        ),
        _record(
            "addr-a",
            address="0x" + ("e" * 40),
            path="deploy/one.sol",
            text="contract AddrA { }",
        ),
        _record(
            "addr-b",
            address="0x" + ("e" * 40),
            path="deploy/two.sol",
            text="contract AddrB { }",
        ),
        _record(
            "path-a",
            source="acme-monorepo",
            path="packages/core/Vault.sol",
            address="0x" + ("f" * 40),
            text="contract PathA { }",
        ),
        _record(
            "path-b",
            source="acme-monorepo",
            path="packages/core/Vault.sol",
            address="0x" + ("11" * 20),
            text="contract PathB { }",
        ),
        _record(
            "fork-a",
            fork_lineage_ids=("fork-family:uniswap-v2",),
            address="0x" + ("22" * 20),
            path="fork/a.sol",
            text="contract ForkA { }",
        ),
        _record(
            "fork-b",
            fork_lineage_ids=("fork-family:uniswap-v2",),
            address="0x" + ("33" * 20),
            path="fork/b.sol",
            text="contract ForkB { }",
        ),
        _record(
            "import-a",
            import_lineage_ids=("import-family:project-local",),
            address="0x" + ("44" * 20),
            path="imp/a.sol",
            text="contract ImportA { }",
        ),
        _record(
            "import-b",
            import_lineage_ids=("import-family:project-local",),
            address="0x" + ("55" * 20),
            path="imp/b.sol",
            text="contract ImportB { }",
        ),
        _record(
            "gen-a",
            generated_code_family_id="codegen:v1",
            address="0x" + ("66" * 20),
            path="gen/a.sol",
            text="contract GenA { }",
        ),
        _record(
            "gen-b",
            generated_code_family_id="codegen:v1",
            address="0x" + ("77" * 20),
            path="gen/b.sol",
            text="contract GenB { }",
        ),
    ]

    first = build_solidity_partitions(
        samples, SolidityPartitionConfig(seed="grouping")
    )
    second = build_solidity_partitions(
        list(reversed(samples)), SolidityPartitionConfig(seed="grouping")
    )

    assert first.digest == second.digest
    assert first.assignments["content-a"] == first.assignments["content-b"]
    assert first.assignments["repo-a"] == first.assignments["repo-b"]
    assert first.assignments["addr-a"] == first.assignments["addr-b"]
    assert first.assignments["path-a"] == first.assignments["path-b"]
    assert first.assignments["fork-a"] == first.assignments["fork-b"]
    assert first.assignments["import-a"] == first.assignments["import-b"]
    assert first.assignments["gen-a"] == first.assignments["gen-b"]
    assert first.guard_result().passed is True
    assert first.duplicate_families
    assert all(isinstance(item, DuplicateFamily) for item in first.duplicate_families)


def test_coarse_etherscan_source_does_not_collapse_unrelated_rows() -> None:
    samples = [
        _record(
            "solo-a",
            source="etherscan",
            address="0x" + ("a1" * 20),
            path="a.sol",
            text="contract SoloA { uint256 a; }",
        ),
        _record(
            "solo-b",
            source="etherscan",
            address="0x" + ("b2" * 20),
            path="b.sol",
            text="contract SoloB { uint256 b; }",
        ),
    ]
    manifest = build_solidity_partitions(
        samples, SolidityPartitionConfig(seed="coarse")
    )
    # Distinct content+address means independent groups; they may still land
    # in the same partition by chance, but they are not forced into one family.
    family_members = {
        frozenset(family.sample_ids) for family in manifest.duplicate_families
    }
    assert frozenset({"solo-a", "solo-b"}) not in family_members


def test_upstream_train_split_is_never_randomly_row_split() -> None:
    config = SolidityPartitionConfig(seed="policy")
    assert config.source_split == "train"
    assert config.source_split == SOLIDITY_CPT_SPLIT
    assert config.source_split == UPSTREAM_SOURCE_SPLIT
    assert config.to_dict()["upstream_split_policy"] == "never_random_row_split"
    assert config.source_dataset_id == SOLIDITY_CPT_DATASET_ID
    assert config.source_revision == SOLIDITY_CPT_REVISION

    samples = [
        _record(f"row-{index}", address="0x" + f"{index:040x}", text=f"c{index} {{ }}")
        for index in range(6)
    ]
    manifest = build_solidity_partitions(samples, config)
    assert manifest.metadata["upstream_split_policy"] == "never_random_row_split"
    assert manifest.metadata["source_revision"] == SOLIDITY_CPT_REVISION
    assert manifest.config_digest == config.digest
    assert manifest.config_digest.startswith("sha256:")


def test_held_out_and_adversarial_apply_to_whole_connected_groups() -> None:
    manifest = build_solidity_partitions(
        [
            _record(
                "domain-a",
                domain="defi-lending",
                repository_id="https://github.com/held/domain",
                address="0x" + ("aa" * 20),
                text="contract DomainA { }",
            ),
            _record(
                "domain-variant",
                domain="general",
                repository_id="https://github.com/held/domain",
                address="0x" + ("bb" * 20),
                text="contract DomainVariant { }",
            ),
            _record(
                "adv-a",
                adversarial=True,
                address="0x" + ("cc" * 20),
                text="contract AdvA { }",
            ),
            _record(
                "adv-linked",
                address="0x" + ("cc" * 20),
                text="contract AdvLinked { }",
            ),
            _record(
                "addr-hold",
                address="0x" + ("dd" * 20),
                text="contract AddrHold { }",
            ),
        ],
        SolidityPartitionConfig(
            seed="holdouts",
            held_out_domains=("defi-lending",),
            held_out_addresses=("0x" + ("dd" * 20),),
        ),
    )

    assert manifest.assignments["domain-a"] == HELD_OUT_PARTITION
    assert manifest.assignments["domain-variant"] == HELD_OUT_PARTITION
    assert manifest.assignments["adv-a"] == ADVERSARIAL_PARTITION
    assert manifest.assignments["adv-linked"] == ADVERSARIAL_PARTITION
    assert manifest.assignments["addr-hold"] == HELD_OUT_PARTITION


def test_manifest_is_source_free_and_cid_bound() -> None:
    samples = [
        _record(
            "copy-a",
            address="0x" + ("ee" * 20),
            content_sha256="c" * 64,
            text=SECRET,
            path="shared/Vault.sol",
            source="acme-protocol",
        ),
        _record(
            "copy-b",
            address="0x" + ("ee" * 20),
            content_sha256="c" * 64,
            text=SECRET.lower() + " /* trailing */",
            path="shared/Vault.sol",
            source="acme-protocol",
        ),
    ]
    config = SolidityPartitionConfig(
        seed="tamper",
        policy_digest="sha256:" + ("d" * 64),
        source_snapshot_cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    )
    manifest = build_solidity_partitions(samples, config)
    serialized = manifest.to_json()

    assert SECRET not in serialized
    assert "secretDrain" not in serialized
    assert "function" not in serialized or "secretDrain" not in serialized
    payload = manifest.to_dict(include_digest=False)
    assert "text" not in json.dumps(payload)
    assert payload["metadata"]["policy_digest"].startswith("sha256:")
    assert payload["metadata"]["source_revision"] == SOLIDITY_CPT_REVISION
    assert payload["config_digest"] == config.digest

    payload["assignments"]["copy-a"] = TRAIN_PARTITION
    payload["assignments"]["copy-b"] = TEST_PARTITION
    result = validate_solidity_partitions(payload)
    assert result.passed is False
    assert {item.kind for item in result.violations} >= {
        "address",
        "content",
        "near_duplicate",
    }
    with pytest.raises(SolidityPartitionLeakageError):
        require_leakage_safe_partitions(payload)


def test_missing_grouping_evidence_fails_closed() -> None:
    with pytest.raises(SolidityPartitionError, match="grouping evidence"):
        SolidityPartitionExample(sample_id="empty-only")


def test_source_revision_drift_fails_closed() -> None:
    with pytest.raises(SolidityPartitionError, match="source_revision"):
        SolidityPartitionConfig(source_revision="0" * 40)
    with pytest.raises(SolidityPartitionError, match="source_dataset_id"):
        SolidityPartitionConfig(source_dataset_id="other/dataset")
    with pytest.raises(SolidityPartitionError, match="source_split"):
        SolidityPartitionConfig(source_split="validation")


def test_assignment_overlap_in_projection_fails_closed() -> None:
    examples = (
        SolidityPartitionExample.from_sample(_record("one")),
        SolidityPartitionExample.from_sample(_record("two")),
    )
    payload = {
        "config_digest": "sha256:" + ("a" * 64),
        "examples": [item.to_dict() for item in examples],
        "partitions": list(SOLIDITY_PARTITIONS),
        "samples_by_partition": {
            "train": ["one", "two"],
            "test": ["one"],
        },
        "schema_version": "solidity-cpt-partition-manifest/v1",
        "metadata": {
            "seed": "overlap",
            "source_dataset_id": SOLIDITY_CPT_DATASET_ID,
            "source_revision": SOLIDITY_CPT_REVISION,
            "source_split": "train",
            "upstream_split_policy": "never_random_row_split",
        },
    }
    result = validate_solidity_partitions(payload)
    assert result.passed is False
    assert any(item.kind == "assignment" for item in result.violations)


def test_retrieval_fence_rejects_cross_partition_family_and_snapshot() -> None:
    source_by_id = {
        "query": "acme-protocol",
        "same": "acme-protocol",
        "cross": "train-only-protocol",
        "stale": "acme-protocol",
        "cross-family": "other-protocol",
    }
    examples = tuple(
        SolidityPartitionExample.from_sample(
            _record(
                sample_id,
                source=source_by_id[sample_id],
                address="0x" + f"{index:040x}",
                text=f"contract C{index} {{ }}",
            )
        )
        for index, sample_id in enumerate(
            ("query", "same", "cross", "stale", "cross-family")
        )
    )
    examples = tuple(
        replace(item, graph_snapshot_id="graph:stale")
        if item.sample_id == "stale"
        else item
        for item in examples
    )
    manifest = SolidityPartitionManifest(
        examples=examples,
        assignments={
            "query": TEST_PARTITION,
            "same": TEST_PARTITION,
            "cross": TRAIN_PARTITION,
            "stale": TEST_PARTITION,
            "cross-family": TEST_PARTITION,
        },
        config_digest="sha256:" + ("a" * 64),
        metadata={
            "seed": "fence",
            "source_dataset_id": SOLIDITY_CPT_DATASET_ID,
            "source_revision": SOLIDITY_CPT_REVISION,
            "source_split": "train",
            "upstream_split_policy": "never_random_row_split",
        },
    )

    allowed = require_retrieval_partition_fence(manifest, "query", ("same",))
    assert allowed.partition == TEST_PARTITION
    assert allowed.graph_snapshot_id == "graph:snapshot-1"
    assert allowed.source_snapshot_cid

    result = validate_retrieval_partition_fence(
        manifest, "query", ("cross", "stale", "missing", "cross-family")
    )
    assert result.passed is False
    assert {item.reason for item in result.violations} >= {
        "candidate_not_in_manifest",
        "cross_partition",
        "graph_snapshot_mismatch",
        "cross_source_family",
    }
    with pytest.raises(SolidityRetrievalFenceError):
        require_retrieval_partition_fence(manifest, "query", ("cross",))


def test_partition_contracts_are_immutable_and_round_trip() -> None:
    manifest = build_solidity_partitions(
        [
            _record("one", address="0x" + ("01" * 20), text="contract One { }"),
            _record("two", address="0x" + ("02" * 20), text="contract Two { }"),
        ]
    )
    decoded = SolidityPartitionManifest.from_dict(json.loads(manifest.to_json()))

    assert decoded.digest == manifest.digest
    assert set(decoded.partitions) == set(SOLIDITY_PARTITIONS)
    assert TRAIN_PARTITION in decoded.partitions
    assert VALIDATION_PARTITION in decoded.partitions
    with pytest.raises(TypeError):
        decoded.assignments["one"] = TEST_PARTITION  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        decoded.config_digest = "changed"  # type: ignore[misc]


def test_duplicate_family_evidence_is_hashed_and_bounded() -> None:
    family = DuplicateFamily(
        family_id="group-1",
        kind="connected_component",
        sample_ids=("a", "b", "a"),
    )
    assert family.sample_ids == ("a", "b")
    assert family.evidence_digest.startswith("sha256:")
    wire = family.to_dict()
    assert DuplicateFamily.from_dict(wire).evidence_digest == family.evidence_digest
    with pytest.raises(SolidityPartitionError):
        DuplicateFamily(
            family_id="solo",
            kind="connected_component",
            sample_ids=("only",),
        )
