"""EAAEF-064: federated retrieval provenance envelope; untrusted similarity cannot override truth."""

from __future__ import annotations

import sys
from pathlib import Path

_DATASETS_ROOT = Path(__file__).resolve().parents[2] / "ipfs_datasets_py"
if str(_DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DATASETS_ROOT))

from ipfs_datasets_py.retrieval.agent_work_contracts import (
    EvidenceClass,
    FederatedRetrievalHit,
    SourceDomain,
    TrustClass,
)
from ipfs_datasets_py.retrieval.agent_work_federation import federate


REQUIRED_ENVELOPE_FIELDS = (
    "cid",
    "revision",
    "trust",
    "mode",
    "score",
    "path",
    "span",
    "capsule",
    "freshness",
    "reason",
)

DIGEST_TRUTH = "sha256:" + ("ab" * 32)
DIGEST_CLAIM = "sha256:" + ("cd" * 32)


def _hit(**changes: object) -> FederatedRetrievalHit:
    values: dict[str, object] = {
        "identity": DIGEST_TRUTH,
        "engine": "ast",
        "evidence_class": EvidenceClass.REPOSITORY_TRUTH,
        "source_domain": SourceDomain.REPOSITORY_TRUTH,
        "path": "src/module.py",
        "bytes_used": 128,
        "trust": TrustClass.LOCALLY_REVERIFIED,
        "retrieved_at": "2026-08-22T00:00:00Z",
        "effective_from": "2026-01-01T00:00:00Z",
        "reason": "current repository truth",
    }
    values.update(changes)
    return FederatedRetrievalHit.from_mapping(values)


def qualify_hit(hit: FederatedRetrievalHit, extra: dict[str, object]) -> dict[str, object]:
    """Qualification envelope requiring provenance fields the hit type does not carry."""

    envelope = {
        "cid": extra["cid"],
        "revision": extra["revision"],
        "trust": extra["trust"],
        "mode": extra["mode"],
        "score": extra["score"],
        "path": extra["path"],
        "span": extra["span"],
        "capsule": extra["capsule"],
        "freshness": extra["freshness"],
        "reason": extra["reason"],
        "hit": hit.to_dict(),
    }
    missing = [name for name in REQUIRED_ENVELOPE_FIELDS if envelope.get(name) in (None, "")]
    if missing:
        raise AssertionError(f"qualification envelope missing {missing}")
    assert envelope["cid"] == hit.identity
    assert envelope["path"] == hit.path
    assert envelope["reason"] == hit.reason
    assert envelope["trust"] == hit.trust.value
    return envelope


def admitted_truth(hits: tuple[FederatedRetrievalHit, ...]) -> tuple[FederatedRetrievalHit, ...]:
    """Untrusted imported claims cannot override repository_truth, regardless of score."""

    selected: list[FederatedRetrievalHit] = []
    for hit in hits:
        untrusted_claim = (
            hit.evidence_class is EvidenceClass.IMPORTED_CLAIM
            and hit.trust.rank < TrustClass.LOCALLY_REVERIFIED.rank
        )
        if untrusted_claim:
            assert hit.trust.may_satisfy_completion is False
            continue
        if hit.evidence_class is EvidenceClass.REPOSITORY_TRUTH:
            selected.append(hit)
    return tuple(selected)


def test_every_item_carries_qualification_envelope_fields() -> None:
    truth = _hit()
    claim = _hit(
        identity=DIGEST_CLAIM,
        engine="vector",
        evidence_class=EvidenceClass.IMPORTED_CLAIM,
        source_domain=SourceDomain.IMPORTED_CLAIMS,
        path="imported/history.md",
        trust=TrustClass.UNTRUSTED,
        reason="untrusted similarity",
    )
    for hit in (truth, claim):
        assert hit.identity.startswith("sha256:")
        assert hit.engine.value
        assert hit.evidence_class.value
        assert hit.source_domain.value
        assert hit.path
        assert hit.bytes_used > 0
        assert hit.trust.value
        assert hit.retrieved_at
        assert hit.effective_from
        assert hit.reason
    truth_env = qualify_hit(
        truth,
        {
            "cid": truth.identity,
            "revision": "git:deadbeef",
            "trust": truth.trust.value,
            "mode": "ast",
            "score": 12,
            "path": truth.path,
            "span": "10:24",
            "capsule": "capsule:module.py",
            "freshness": truth.retrieved_at,
            "reason": truth.reason,
        },
    )
    claim_env = qualify_hit(
        claim,
        {
            "cid": claim.identity,
            "revision": "imported:rev-1",
            "trust": claim.trust.value,
            "mode": "vector",
            "score": 99,
            "path": claim.path,
            "span": "1:4",
            "capsule": "capsule:imported",
            "freshness": claim.retrieved_at,
            "reason": claim.reason,
        },
    )
    for envelope in (truth_env, claim_env):
        for name in REQUIRED_ENVELOPE_FIELDS:
            assert envelope[name] not in (None, "")
    report = federate(({"engine": "ast"}, {"engine": "vector"}))
    assert report["duplicate_index_system"] is False


def test_untrusted_similarity_cannot_override_repository_truth() -> None:
    truth = _hit(reason="repository_truth wins")
    claim = _hit(
        identity=DIGEST_CLAIM,
        engine="vector",
        evidence_class=EvidenceClass.IMPORTED_CLAIM,
        source_domain=SourceDomain.IMPORTED_CLAIMS,
        path="imported/history.md",
        trust=TrustClass.IMPORTED_UNVERIFIED,
        reason="high similarity imported claim",
    )
    truth_env = qualify_hit(
        truth,
        {
            "cid": truth.identity,
            "revision": "git:1",
            "trust": truth.trust.value,
            "mode": "ast",
            "score": 4,
            "path": truth.path,
            "span": "0:1",
            "capsule": "capsule:truth",
            "freshness": truth.retrieved_at,
            "reason": truth.reason,
        },
    )
    claim_env = qualify_hit(
        claim,
        {
            "cid": claim.identity,
            "revision": "import:9",
            "trust": claim.trust.value,
            "mode": "vector",
            "score": 10_000,
            "path": claim.path,
            "span": "0:9",
            "capsule": "capsule:claim",
            "freshness": claim.retrieved_at,
            "reason": claim.reason,
        },
    )
    assert claim_env["score"] > truth_env["score"]
    admitted = admitted_truth((truth, claim))
    assert [item.identity for item in admitted] == [truth.identity]
    assert all(item.evidence_class is EvidenceClass.REPOSITORY_TRUTH for item in admitted)
    assert claim.trust.may_satisfy_completion is False
    assert TrustClass.UNTRUSTED.rank < TrustClass.LOCALLY_REVERIFIED.rank
