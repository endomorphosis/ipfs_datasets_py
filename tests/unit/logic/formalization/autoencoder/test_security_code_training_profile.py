"""Canonical sources, code-family capabilities and dependency-gated native plans."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security.security_code_training_profile import (
    build_security_code_training_profile, validate_security_code_training_profile,
)
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_cve_corpus import build_security_corpus_profile
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_cve_training_source import BenchmarkExclusions
from ipfs_datasets_py.logic.formalization.autoencoder.security.published_legal_initializer import PIN_SCHEMA
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_source import HuggingFaceSourcePin
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
def content_identity(value):
    return canonical_identity(value, domain="autoencoder/security-training", schema_version="security-code-training-profile@1").cid


@pytest.fixture
def profile():
    root = canonical_identity({"fixture": "security-profile"}, domain="authored", schema_version="v1").cid
    corpus = build_security_corpus_profile(pin=HuggingFaceSourcePin(revision="1" * 40,
        manifest_sha256="2" * 64, release_root=root),
        repository_splits={split: ["https://github.com/authored/" + split] for split in ("train", "validation", "test")},
        graph_shards=["data/graph/nodes/part-000000.parquet"],
        exclusions=BenchmarkExclusions(source_families=("https://github.com/bottlepy/bottle",),
            file_names=("bottle.py",), code_sha256=("3" * 64,)))
    parent = {"schema": PIN_SCHEMA, "repo_id": "justicedao/legal-ir-autoencoder-checkpoints",
        "revision": "4" * 40, "manifest_path": "checkpoints/20260101T000000Z/manifest.json",
        "manifest_sha256": "5" * 64, "readme_sha256": "6" * 64,
        "checkpoint_id": "20260101T000000Z",
        "state_path": "checkpoints/20260101T000000Z/state/legal-ir-autoencoder-canonical.state.json",
        "state_sha256": "7" * 64, "state_bytes": 1234, "source_records_sha256": "8" * 64,
        "source_count": 1, "source_git_commit": "9" * 40}
    return build_security_code_training_profile(corpus_profile=corpus, legal_parent=parent)


def test_code_targets_use_native_families_and_keep_shared_weights_separate(profile):
    assert validate_security_code_training_profile(profile) == profile
    views = {row["kind"]: row for row in profile["code_logic"]["projections"]}
    assert (views["contract"]["family"], views["contract"]["profile"]) == ("program", "dynamic_hoare")
    assert views["transition"]["family"] == "transition_system"
    assert views["separation"]["family"] == "separation_logic"
    assert views["hyperproperty"]["family"] == "hyperproperty"
    assert profile["code_logic"]["tla_encoding"]["encoding"] == "tla+"
    assert all(row["family"] not in {"tla+", "verification_condition", "information_flow"} for row in views.values())
    assert not profile["initialization"]["legal_heads_reused_as_code_heads"]
    assert not profile["initialization"]["legal_checkpoint_writes"]
    assert not profile["initialization"]["random_backbone_initialization"]


@pytest.mark.parametrize("change", ["mutable_parent", "wrong_parent", "mixed_split", "invented_family", "proved", "trained"])
def test_source_split_or_capability_changes_require_a_new_valid_profile(profile, change):
    altered = deepcopy(profile)
    if change == "mutable_parent": altered["legal_parent"]["revision"] = "main"
    elif change == "wrong_parent": altered["legal_parent"]["repo_id"] = "other/checkpoints"
    elif change == "mixed_split": altered["corpus"]["repository_splits"]["test"] = altered["corpus"]["repository_splits"]["train"]
    elif change == "invented_family": altered["code_logic"]["projections"][0]["family"] = "tla+"
    elif change == "proved": altered["proof_authority"] = True
    else: altered["training"]["formula_head_trained"] = True
    altered["profile_cid"] = content_identity({key: value for key, value in altered.items() if key != "profile_cid"})
    with pytest.raises(ValueError): validate_security_code_training_profile(altered)
