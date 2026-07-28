"""Unit tests for ProofCorpusQuery@1 and rebuildable secondary indexes.

Acceptance (LIG-012): deterministic query results; index rebuild matches.
Queries cover source, family, obligation digest, and profile filters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus.index import (
    PROOF_CORPUS_INDEX_INTERFACE,
    ProofCorpusIndex,
    ProofCorpusIndexError,
    ProofCorpusIndexIntegrityError,
    load_store_index,
    normalize_obligation_digest,
    obligation_digests_for_envelope,
    rebuild_index_from_store,
)
from ipfs_datasets_py.logic.proof_corpus.query import (
    PROOF_CORPUS_QUERY_INTERFACE,
    PROOF_CORPUS_QUERY_SCHEMA_VERSION,
    ProofCorpusQuery,
    ProofCorpusQueryError,
    get_by_cid,
    list_by_source,
    list_constraints_for_obligation,
    query_corpus,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import (
    PROOF_CORPUS_INDEX_SCHEMA_VERSION,
    ArtifactEnvelope,
    ProofCorpusFamily,
)
from ipfs_datasets_py.logic.proof_corpus.store import (
    ProofCorpusStore,
    ProofCorpusStoreError,
    put_family_fixtures,
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


def _populated_store() -> tuple[
    ProofCorpusStore, ArtifactEnvelope, ArtifactEnvelope, ArtifactEnvelope
]:
    store = ProofCorpusStore()
    intent, legal, security = put_family_fixtures(
        store,
        intent_artifact=_intent_artifact(),
        intent_profile=_intent_profile(),
        legal_record=_legal_record(),
        security_record=_security_record(),
    )
    return store, intent, legal, security


def _query_with_index(
    store: ProofCorpusStore,
) -> ProofCorpusQuery:
    return ProofCorpusQuery(store=store, index=rebuild_index_from_store(store))


# ---------------------------------------------------------------------------
# Interface / index rebuild
# ---------------------------------------------------------------------------


def test_query_interface_and_schema_are_pinned() -> None:
    store, _, _, _ = _populated_store()
    query = ProofCorpusQuery(store=store)
    assert query.interface == PROOF_CORPUS_QUERY_INTERFACE
    assert query.schema_version == PROOF_CORPUS_QUERY_SCHEMA_VERSION
    assert PROOF_CORPUS_QUERY_INTERFACE == "ProofCorpusQuery@1"
    assert PROOF_CORPUS_QUERY_SCHEMA_VERSION == "proof-corpus-query/v1"


def test_index_rebuild_is_deterministic() -> None:
    store, intent, legal, security = _populated_store()
    first = rebuild_index_from_store(store)
    second = ProofCorpusIndex.build((intent, legal, security))
    third = ProofCorpusIndex.from_store(store)

    assert first.to_dict() == second.to_dict() == third.to_dict()
    assert first.to_dict() == ProofCorpusIndex.build(
        (security, intent, legal)  # order-independent
    ).to_dict()
    assert first.interface == PROOF_CORPUS_INDEX_INTERFACE
    assert first.schema_version == PROOF_CORPUS_INDEX_SCHEMA_VERSION
    assert len(first) == 3
    assert set(first.families) == {"intent", "legal", "security"}


def test_index_rebuild_matches_store_on_disk_index(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-query"
    store = ProofCorpusStore(root=root)
    intent, legal, security = put_family_fixtures(
        store,
        intent_artifact=_intent_artifact(),
        intent_profile=_intent_profile(),
        legal_record=_legal_record(),
        security_record=_security_record(),
    )
    assert {intent.family.value, legal.family.value, security.family.value} == {
        "intent",
        "legal",
        "security",
    }

    rebuilt = rebuild_index_from_store(store)
    on_disk = load_store_index(root / "index.json")
    assert rebuilt.matches_store_index(on_disk)
    assert rebuilt.to_store_index_dict()["families"] == on_disk["families"]
    assert rebuilt.to_store_index_dict()["sources"] == on_disk["sources"]
    assert rebuilt.to_store_index_dict()["schema_version"] == on_disk["schema_version"]
    # Store profile postings are put-order last-writer-wins; rebuild keeps
    # multi-valued coverage that includes every store profile CID.
    for profile_key, cid in on_disk["profiles"].items():
        assert cid in rebuilt.profiles[profile_key]


def test_index_round_trip_save_load(tmp_path: Path) -> None:
    store, _, _, _ = _populated_store()
    index = rebuild_index_from_store(store)
    path = tmp_path / "secondary-index.json"
    index.save(path)
    loaded = ProofCorpusIndex.load(path)
    assert loaded.to_dict() == index.to_dict()
    index.assert_matches_envelopes(
        store.get(cid) for cid in store.cids()
    )


def test_index_assert_matches_envelopes_detects_drift() -> None:
    store, intent, legal, security = _populated_store()
    index = rebuild_index_from_store(store)
    # Drop legal from a partial envelope set → rebuild mismatch.
    with pytest.raises(ProofCorpusIndexIntegrityError, match="does not match"):
        index.assert_matches_envelopes((intent, security))


# ---------------------------------------------------------------------------
# Deterministic queries
# ---------------------------------------------------------------------------


def test_get_by_cid_is_deterministic() -> None:
    store, intent, legal, security = _populated_store()
    query = _query_with_index(store)

    for envelope in (intent, legal, security):
        got_a = query.get_by_cid(envelope.content_cid)
        got_b = get_by_cid(store, envelope.content_cid)
        assert got_a.content_cid == got_b.content_cid == envelope.content_cid
        assert got_a.content_digest == envelope.content_digest
        assert got_a.family is envelope.family


def test_list_by_family_is_sorted_and_deterministic() -> None:
    store, intent, legal, security = _populated_store()
    query = _query_with_index(store)

    legal_hits = query.list_by_family(ProofCorpusFamily.LEGAL)
    assert len(legal_hits) == 1
    assert legal_hits[0].content_cid == legal.content_cid

    for family in ("intent", "legal", "security"):
        cids = [env.content_cid for env in query.list_by_family(family)]
        assert cids == sorted(cids)

    all_cids = {env.content_cid for env in query.list_all()}
    assert all_cids == {
        intent.content_cid,
        legal.content_cid,
        security.content_cid,
    }
    list_all_cids = [env.content_cid for env in query.list_all()]
    assert list_all_cids == sorted(list_all_cids)

    # Repeatability
    assert [e.content_cid for e in query.list_by_family("security")] == [
        e.content_cid for e in query.list_by_family(ProofCorpusFamily.SECURITY)
    ]


def test_list_by_source_digest_and_source_id() -> None:
    store, intent, legal, security = _populated_store()
    query = _query_with_index(store)

    by_digest = query.list_by_source(source_digest=intent.source_digest)
    assert len(by_digest) == 1
    assert by_digest[0].content_cid == intent.content_cid

    by_id = query.list_by_source(source_id=legal.source_id)
    assert len(by_id) == 1
    assert by_id[0].content_cid == legal.content_cid

    by_both = query.list_by_source(
        source_digest=security.source_digest,
        source_id=security.source_id,
        profile=security.profile,
        family=ProofCorpusFamily.SECURITY,
    )
    assert len(by_both) == 1
    assert by_both[0].content_cid == security.content_cid

    module_hits = list_by_source(
        store, source_digest=legal.source_digest, profile=legal.profile
    )
    assert [e.content_cid for e in module_hits] == [legal.content_cid]


def test_list_by_source_requires_identity() -> None:
    store, _, _, _ = _populated_store()
    query = _query_with_index(store)
    with pytest.raises(ProofCorpusQueryError, match="source_digest and/or source_id"):
        query.list_by_source()


def test_list_by_profile() -> None:
    store, intent, legal, security = _populated_store()
    query = _query_with_index(store)

    # Intent and legal fixtures intentionally share profile ``legal-strict``;
    # the secondary index is multi-valued so both envelopes are returned.
    assert intent.profile == legal.profile == "legal-strict"
    legal_strict_hits = query.list_by_profile("legal-strict")
    assert {e.content_cid for e in legal_strict_hits} == {
        intent.content_cid,
        legal.content_cid,
    }
    assert [e.content_cid for e in legal_strict_hits] == sorted(
        e.content_cid for e in legal_strict_hits
    )

    security_hits = query.list_by_profile(security.profile)
    assert len(security_hits) == 1
    assert security_hits[0].content_cid == security.content_cid

    assert query.list_by_profile("missing-profile-xyz") == ()


def test_list_by_obligation_and_constraints() -> None:
    store, intent, legal, security = _populated_store()
    query = _query_with_index(store)

    intent_digests = obligation_digests_for_envelope(intent)
    security_digests = obligation_digests_for_envelope(security)
    assert intent_digests, "intent fixture must expose proof obligations"
    assert security_digests, "security fixture must expose proof obligations"
    # Legal fixture currently has zero proof_obligations.
    assert obligation_digests_for_envelope(legal) == ()

    intent_oblig = intent_digests[0]
    security_oblig = security_digests[0]

    # Full family list includes Intent.
    intent_hits = query.list_by_obligation(intent_oblig, family="intent")
    assert len(intent_hits) == 1
    assert intent_hits[0].content_cid == intent.content_cid

    # Default constraint join excludes Intent.
    constraint_for_intent = query.list_constraints_for_obligation(intent_oblig)
    assert constraint_for_intent == ()

    # Security obligation is a constraint hit.
    security_constraints = query.list_constraints_for_obligation(security_oblig)
    assert len(security_constraints) == 1
    assert security_constraints[0].content_cid == security.content_cid
    assert security_constraints[0].family is ProofCorpusFamily.SECURITY

    # Bare hex and sha256: forms both work.
    bare = security_oblig.removeprefix("sha256:")
    assert normalize_obligation_digest(bare) == security_oblig
    again = list_constraints_for_obligation(store, bare)
    assert [e.content_cid for e in again] == [security.content_cid]

    with_intent = query.list_constraints_for_obligation(
        intent_oblig, include_intent=True
    )
    assert len(with_intent) == 1
    assert with_intent[0].family is ProofCorpusFamily.INTENT


def test_composite_query_intersection_is_deterministic() -> None:
    store, intent, legal, security = _populated_store()
    query = _query_with_index(store)

    only_legal = query.query(family="legal")
    assert [e.content_cid for e in only_legal] == [legal.content_cid]

    by_profile_and_family = query.query(
        family="security", profile=security.profile
    )
    assert [e.content_cid for e in by_profile_and_family] == [
        security.content_cid
    ]

    # Shared profile legal-strict + family filter narrows to one family.
    legal_only = query.query(family="legal", profile=intent.profile)
    assert [e.content_cid for e in legal_only] == [legal.content_cid]

    # Disjoint filters yield empty intersection.
    empty = query.query(family="legal", profile=security.profile)
    assert empty == ()

    by_cid = query.query(content_cid=intent.content_cid)
    assert len(by_cid) == 1
    assert by_cid[0].content_cid == intent.content_cid

    module_hits = query_corpus(store, family="intent", source_id=intent.source_id)
    assert [e.content_cid for e in module_hits] == [intent.content_cid]

    # Same inputs → identical CID order across calls.
    first = [e.content_cid for e in query.list_all()]
    second = [e.content_cid for e in query.list_all()]
    assert first == second == sorted(first)
    assert set(first) == {
        intent.content_cid,
        legal.content_cid,
        security.content_cid,
    }


def test_query_requires_at_least_one_filter() -> None:
    store, _, _, _ = _populated_store()
    query = _query_with_index(store)
    with pytest.raises(ProofCorpusQueryError, match="at least one filter"):
        query.query()


def test_rebuild_index_after_put_updates_postings() -> None:
    store = ProofCorpusStore()
    query = ProofCorpusQuery(store=store)
    assert query.list_all() == ()

    intent = ArtifactEnvelope.from_intent_artifact(
        _intent_artifact(), profile=_intent_profile()
    )
    store.put(intent)
    # Auto-index from empty store is stale until rebuild.
    query.rebuild_index()
    hits = query.list_by_family("intent")
    assert len(hits) == 1
    assert hits[0].content_cid == intent.content_cid

    legal = ArtifactEnvelope.from_legal_record(_legal_record())
    store.put(legal)
    query.rebuild_index()
    assert len(query.list_all()) == 2
    assert query.list_by_family("legal")[0].content_cid == legal.content_cid


def test_stats_are_stable() -> None:
    store, _, _, _ = _populated_store()
    query = _query_with_index(store)
    stats = query.stats()
    assert stats["interface"] == PROOF_CORPUS_QUERY_INTERFACE
    assert stats["envelope_count"] == 3
    assert stats["family_count"] == 3
    assert stats["obligation_count"] >= 1
    assert stats["store_size"] == 3


def test_missing_cid_raises_on_get() -> None:
    store, _, _, _ = _populated_store()
    query = _query_with_index(store)
    with pytest.raises(ProofCorpusStoreError, match="not found"):
        query.get_by_cid("bafkrei" + "z" * 52)


def test_normalize_obligation_digest_rejects_garbage() -> None:
    with pytest.raises(ProofCorpusIndexError):
        normalize_obligation_digest("not-a-digest")
    with pytest.raises(ProofCorpusIndexError):
        normalize_obligation_digest("")


def test_duplicate_content_cid_on_rebuild_fails_closed() -> None:
    store, intent, _, _ = _populated_store()
    with pytest.raises(ProofCorpusIndexIntegrityError, match="duplicate"):
        ProofCorpusIndex.build((intent, intent))
