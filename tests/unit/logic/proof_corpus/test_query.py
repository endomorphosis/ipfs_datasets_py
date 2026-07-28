"""Unit tests for ProofCorpusQuery@1 and rebuildable secondary indexes (LIG-012).

Acceptance: deterministic query results; index rebuild matches.
Store is populated in tests via the three offline multi-family fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus import (
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusStore,
    put_family_fixtures,
)
from ipfs_datasets_py.logic.proof_corpus.index import (
    PROOF_CORPUS_INDEX_FILENAME,
    PROOF_CORPUS_SECONDARY_INDEX_FILENAME,
    ProofCorpusIndex,
    ProofCorpusIndexError,
    normalize_obligation_digest,
    rebuild_and_persist,
    rebuild_index,
)
from ipfs_datasets_py.logic.proof_corpus.query import (
    PROOF_CORPUS_QUERY_INTERFACE,
    PROOF_CORPUS_QUERY_SCHEMA_VERSION,
    ProofCorpusQuery,
    ProofCorpusQueryError,
    open_query,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import (
    PROOF_CORPUS_INDEX_SCHEMA_VERSION,
    PROOF_CORPUS_STORE_INTERFACE,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"

INTENT_FIXTURES = FIXTURE_ROOT / "intent_ir" / "admissibility"
LEGAL_FIXTURES = FIXTURE_ROOT / "legal_ir" / "proof_cache"
SECURITY_FIXTURES = FIXTURE_ROOT / "security_ir" / "constraint_cache"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _intent_artifact() -> FormalizationArtifact:
    path = INTENT_FIXTURES / "formal_artifacts" / "benign_skill.json"
    return FormalizationArtifact.from_dict(_load_json(path))


def _intent_profile() -> str:
    case = next(
        item
        for item in _load_json(INTENT_FIXTURES / "manifest.json")["cases"]
        if item["case_id"] == "benign_skill"
    )
    return str(case["profile_id"])


def _legal_record() -> dict[str, Any]:
    return _load_json(LEGAL_FIXTURES / "us_code_552_record.json")


def _security_record() -> dict[str, Any]:
    return _load_json(SECURITY_FIXTURES / "exchange_record.json")


def _populated_store(
    root: Path | None = None,
) -> tuple[ProofCorpusStore, ArtifactEnvelope, ArtifactEnvelope, ArtifactEnvelope]:
    store = ProofCorpusStore(root=root)
    intent, legal, security = put_family_fixtures(
        store,
        intent_artifact=_intent_artifact(),
        intent_profile=_intent_profile(),
        legal_record=_legal_record(),
        security_record=_security_record(),
    )
    return store, intent, legal, security


# ---------------------------------------------------------------------------
# Interface / construction
# ---------------------------------------------------------------------------


def test_query_interface_and_schema_versions_are_pinned() -> None:
    store, _, _, _ = _populated_store()
    query = ProofCorpusQuery(store=store)
    assert query.interface == PROOF_CORPUS_QUERY_INTERFACE
    assert query.schema_version == PROOF_CORPUS_QUERY_SCHEMA_VERSION
    assert PROOF_CORPUS_QUERY_INTERFACE == "ProofCorpusQuery@1"
    assert PROOF_CORPUS_QUERY_SCHEMA_VERSION == "proof-corpus-query/v1"


def test_open_query_helper() -> None:
    store, intent, _, _ = _populated_store()
    query = open_query(store)
    assert query.get_by_cid(intent.content_cid).content_cid == intent.content_cid


# ---------------------------------------------------------------------------
# Index rebuild matches
# ---------------------------------------------------------------------------


def test_index_rebuild_is_deterministic_for_fixed_corpus() -> None:
    store, _, _, _ = _populated_store()
    first = rebuild_index(store)
    second = rebuild_index(store)
    assert first == second
    assert first.to_dict() == second.to_dict()
    # Byte-stable canonical form
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )


def test_index_rebuild_matches_store_index_projection(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus"
    store, _, _, _ = _populated_store(root=root)

    rebuilt = rebuild_index(store)
    store_index = _load_json(root / PROOF_CORPUS_INDEX_FILENAME)
    projection = rebuilt.to_store_dict()

    # Families and sources are multi-key maps with no last-writer collision
    # across distinct sources; they must match the store's on-disk index.
    assert projection["families"] == store_index["families"]
    assert projection["sources"] == store_index["sources"]
    assert projection["schema_version"] == store_index["schema_version"]
    assert projection["interface"] == PROOF_CORPUS_STORE_INTERFACE
    assert store_index["schema_version"] == PROOF_CORPUS_INDEX_SCHEMA_VERSION

    # Bare profile map is last-writer-wins.  Rebuild is envelope-order
    # deterministic (sorted content_cid), matching store.reload() scan order
    # rather than historical put() order when two families share a profile.
    assert set(projection["profiles"]) == set(store_index["profiles"])
    for profile, cid in projection["profiles"].items():
        assert cid in {
            env_cid
            for family_cids in projection["families"].values()
            for env_cid in family_cids
        }
        # Indexed CID must belong to an envelope that carries that profile.
        assert store.get(cid).profile == profile


def test_index_rebuild_after_discard_matches_previous(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-rebuild"
    store, _, _, _ = _populated_store(root=root)

    original = rebuild_and_persist(store)
    secondary_path = root / PROOF_CORPUS_SECONDARY_INDEX_FILENAME
    assert secondary_path.is_file()

    # Discard secondary index and rebuild from envelopes only.
    secondary_path.unlink()
    (root / PROOF_CORPUS_INDEX_FILENAME).unlink()

    reloaded_store = ProofCorpusStore(root=root)
    rebuilt = rebuild_and_persist(reloaded_store)

    assert rebuilt.to_dict() == original.to_dict()
    assert rebuilt.to_store_dict() == original.to_store_dict()


def test_index_build_order_independent() -> None:
    store, intent, legal, security = _populated_store()
    a = ProofCorpusIndex.build([intent, legal, security])
    b = ProofCorpusIndex.build([security, intent, legal])
    c = ProofCorpusIndex.build([legal, security, intent])
    assert a == b == c


def test_index_round_trip_dict() -> None:
    store, _, _, _ = _populated_store()
    index = rebuild_index(store)
    restored = ProofCorpusIndex.from_dict(index.to_dict())
    assert restored == index
    assert restored.obligations == index.obligations


def test_index_from_store_reloads_disk(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-from-store"
    store, intent, legal, security = _populated_store(root=root)
    index = ProofCorpusIndex.from_store(store)
    assert set(index.all_cids()) == {
        intent.content_cid,
        legal.content_cid,
        security.content_cid,
    }
    assert "intent" in index.families
    assert "legal" in index.families
    assert "security" in index.families


def test_index_unsupported_schema_fails_closed() -> None:
    with pytest.raises(ProofCorpusIndexError, match="unsupported"):
        ProofCorpusIndex.from_dict(
            {
                "schema_version": "proof-corpus-index/v0",
                "families": {},
                "profiles": {},
                "sources": {},
            }
        )


def test_normalize_obligation_digest_accepts_sha256_prefix() -> None:
    bare = "a" * 64
    assert normalize_obligation_digest(bare) == bare
    assert normalize_obligation_digest(f"sha256:{bare}") == bare
    with pytest.raises(ProofCorpusIndexError):
        normalize_obligation_digest("not-a-digest")


# ---------------------------------------------------------------------------
# Deterministic query results
# ---------------------------------------------------------------------------


def test_get_by_cid_returns_verified_envelope() -> None:
    store, intent, legal, security = _populated_store()
    query = ProofCorpusQuery(store=store)

    for env in (intent, legal, security):
        got = query.get_by_cid(env.content_cid)
        assert got.content_cid == env.content_cid
        assert got.content_digest == env.content_digest
        assert got.family is env.family


def test_get_by_cid_missing_raises() -> None:
    store, _, _, _ = _populated_store()
    query = ProofCorpusQuery(store=store)
    with pytest.raises(ProofCorpusQueryError, match="not found"):
        query.get_by_cid("bafkreimissing" + "a" * 40)


def test_list_by_family_deterministic() -> None:
    store, intent, legal, security = _populated_store()
    query = ProofCorpusQuery(store=store)

    first = query.list_by_family(ProofCorpusFamily.LEGAL)
    second = query.list_by_family("legal")
    assert first == second
    assert len(first) == 1
    assert first[0].content_cid == legal.content_cid

    intent_list = query.list_by_family("intent")
    security_list = query.list_by_family("security")
    assert [e.content_cid for e in intent_list] == [intent.content_cid]
    assert [e.content_cid for e in security_list] == [security.content_cid]


def test_list_by_source_deterministic() -> None:
    store, intent, legal, security = _populated_store()
    query = ProofCorpusQuery(store=store)

    by_legal_source = query.list_by_source(legal.source_digest)
    assert len(by_legal_source) == 1
    assert by_legal_source[0].content_cid == legal.content_cid

    # Same query twice → identical sequence
    again = query.list_by_source(legal.source_digest)
    assert [e.content_cid for e in again] == [
        e.content_cid for e in by_legal_source
    ]

    with_profile = query.list_by_source(
        security.source_digest, profile=security.profile
    )
    assert len(with_profile) == 1
    assert with_profile[0].content_cid == security.content_cid

    wrong_family = query.list_by_source(
        intent.source_digest, family=ProofCorpusFamily.LEGAL
    )
    assert wrong_family == ()


def test_list_by_profile_deterministic() -> None:
    store, _, legal, security = _populated_store()
    query = ProofCorpusQuery(store=store)

    # legal and intent fixtures may share profile keys; security is unique.
    sec_list = query.list_by_profile(security.profile)
    assert len(sec_list) == 1
    assert sec_list[0].content_cid == security.content_cid

    legal_list = query.list_by_profile(legal.profile)
    assert len(legal_list) >= 1
    assert all(e.profile == legal.profile for e in legal_list)
    # Deterministic ordering
    assert [e.content_cid for e in legal_list] == sorted(
        e.content_cid for e in legal_list
    )


def test_list_constraints_for_obligation_by_digest() -> None:
    store, intent, legal, security = _populated_store()
    query = ProofCorpusQuery(store=store)

    # Security fixture carries at least one proof obligation.
    sec_artifact = security.formalization_artifact()
    assert sec_artifact.proof_obligations, "security fixture must have obligations"
    obligation = sec_artifact.proof_obligations[0]
    digest = obligation.digest

    constraints = query.list_constraints_for_obligation(digest)
    assert len(constraints) == 1
    assert constraints[0].content_cid == security.content_cid
    assert constraints[0].family is ProofCorpusFamily.SECURITY

    # Default filter excludes Intent even if the digest matched an Intent ob.
    intent_artifact = intent.formalization_artifact()
    assert intent_artifact.proof_obligations
    intent_digest = intent_artifact.proof_obligations[0].digest
    intent_as_constraint = query.list_constraints_for_obligation(intent_digest)
    assert intent_as_constraint == ()

    # Explicit all-families includes Intent.
    all_families = query.list_constraints_for_obligation(
        intent_digest, families=None
    )
    assert len(all_families) == 1
    assert all_families[0].content_cid == intent.content_cid

    # Legal fixture has no obligations → empty for its digests of intent.
    legal_constraints = query.list_constraints_for_obligation(
        digest, families=("legal",)
    )
    assert legal_constraints == ()


def test_list_constraints_for_obligation_by_id() -> None:
    store, _, _, security = _populated_store()
    query = ProofCorpusQuery(store=store)
    obligation = security.formalization_artifact().proof_obligations[0]

    by_id = query.list_constraints_for_obligation(
        obligation_id=obligation.obligation_id
    )
    assert len(by_id) == 1
    assert by_id[0].content_cid == security.content_cid

    # Intersection of digest + id
    both = query.list_constraints_for_obligation(
        obligation.digest, obligation_id=obligation.obligation_id
    )
    assert both == by_id


def test_list_constraints_requires_selector() -> None:
    store, _, _, _ = _populated_store()
    query = ProofCorpusQuery(store=store)
    with pytest.raises(ProofCorpusQueryError, match="requires obligation"):
        query.list_constraints_for_obligation()


def test_query_results_stable_across_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-stable-query"
    store, intent, legal, security = _populated_store(root=root)
    query = ProofCorpusQuery(store=store)

    before = {
        "by_family_legal": [e.content_cid for e in query.list_by_family("legal")],
        "by_source": [
            e.content_cid for e in query.list_by_source(security.source_digest)
        ],
        "by_cid": query.get_by_cid(intent.content_cid).content_digest,
        "all": [e.content_cid for e in query.list_all()],
    }
    if security.formalization_artifact().proof_obligations:
        dig = security.formalization_artifact().proof_obligations[0].digest
        before["by_ob"] = [
            e.content_cid for e in query.list_constraints_for_obligation(dig)
        ]

    # Rebuild index and re-run the same queries.
    query.rebuild_index(persist=True)
    after = {
        "by_family_legal": [e.content_cid for e in query.list_by_family("legal")],
        "by_source": [
            e.content_cid for e in query.list_by_source(security.source_digest)
        ],
        "by_cid": query.get_by_cid(intent.content_cid).content_digest,
        "all": [e.content_cid for e in query.list_all()],
    }
    if "by_ob" in before:
        dig = security.formalization_artifact().proof_obligations[0].digest
        after["by_ob"] = [
            e.content_cid for e in query.list_constraints_for_obligation(dig)
        ]

    assert before == after
    assert before["by_family_legal"] == [legal.content_cid]
    assert before["all"] == sorted(
        [intent.content_cid, legal.content_cid, security.content_cid]
    )


def test_multi_filter_query_helper() -> None:
    store, intent, legal, security = _populated_store()
    query = ProofCorpusQuery(store=store)

    assert query.query(content_cid=legal.content_cid)[0].content_cid == (
        legal.content_cid
    )
    assert query.query(family="security")[0].content_cid == security.content_cid
    assert query.query(source_digest=intent.source_digest)[0].content_cid == (
        intent.content_cid
    )

    dig = security.formalization_artifact().proof_obligations[0].digest
    assert query.query(obligation_digest=dig)[0].content_cid == security.content_cid


def test_query_stats_track_hits() -> None:
    store, intent, _, _ = _populated_store()
    query = ProofCorpusQuery(store=store)
    query.get_by_cid(intent.content_cid)
    with pytest.raises(ProofCorpusQueryError):
        query.get_by_cid("bafkreimissing" + "b" * 40)
    stats = query.stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["store_size"] == 3
    assert stats["index_size"] == 3


def test_empty_store_queries_are_empty() -> None:
    store = ProofCorpusStore()
    query = ProofCorpusQuery(store=store)
    assert query.list_by_family("legal") == ()
    assert query.list_all() == ()
    assert query.list_by_profile("dev-offline") == ()


def test_index_in_memory_matches_disk_store(tmp_path: Path) -> None:
    mem_store, *_ = _populated_store()
    disk_store, *_ = _populated_store(root=tmp_path / "disk")
    mem_index = rebuild_index(mem_store)
    disk_index = rebuild_index(disk_store)
    # Same fixtures → same index content regardless of backend.
    assert mem_index.to_dict() == disk_index.to_dict()


def test_obligation_index_populated_for_intent_and_security() -> None:
    store, intent, legal, security = _populated_store()
    index = rebuild_index(store)

    intent_obs = intent.formalization_artifact().proof_obligations
    security_obs = security.formalization_artifact().proof_obligations
    legal_obs = legal.formalization_artifact().proof_obligations

    for ob in intent_obs:
        cids = index.cids_for_obligation_digest(ob.digest)
        assert intent.content_cid in cids
    for ob in security_obs:
        cids = index.cids_for_obligation_digest(ob.digest)
        assert security.content_cid in cids
    # Legal fixture currently has zero obligations; index must still be valid.
    assert isinstance(legal_obs, tuple)
    for digests in index.obligations.values():
        assert digests == sorted(digests)


def test_rebuild_index_method_on_query(tmp_path: Path) -> None:
    root = tmp_path / "query-rebuild"
    store, _, _, _ = _populated_store(root=root)
    query = ProofCorpusQuery(store=store, auto_rebuild=False, index=ProofCorpusIndex.empty())
    assert len(query.index or ProofCorpusIndex.empty()) == 0

    rebuilt = query.rebuild_index(persist=True)
    assert len(rebuilt) == 3
    assert (root / PROOF_CORPUS_SECONDARY_INDEX_FILENAME).is_file()
    loaded = ProofCorpusIndex.load(root)
    assert loaded.to_dict() == rebuilt.to_dict()
