"""Unit tests for ProofCorpusStore@1 put/get integrity across three families.

Acceptance (LIG-011): store accepts three family fixtures; corruption fails
closed.  Fixtures remain owned by Intent/Legal/Security packages; this module
only adapts them into unified envelopes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus import (
    PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION,
    PROOF_CORPUS_STORE_INTERFACE,
    PROOF_CORPUS_STORE_SCHEMA_VERSION,
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusIntegrityError,
    ProofCorpusSchemaError,
    ProofCorpusStore,
    ProofCorpusStoreError,
    ProofCorpusStoreIntegrityError,
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


def _three_envelopes() -> tuple[ArtifactEnvelope, ArtifactEnvelope, ArtifactEnvelope]:
    intent = ArtifactEnvelope.from_intent_artifact(
        _intent_artifact(), profile=_intent_profile()
    )
    legal = ArtifactEnvelope.from_legal_record(_legal_record())
    security = ArtifactEnvelope.from_security_record(_security_record())
    return intent, legal, security


# ---------------------------------------------------------------------------
# Schema / envelope construction
# ---------------------------------------------------------------------------


def test_interface_and_schema_versions_are_pinned() -> None:
    store = ProofCorpusStore()
    assert store.interface == PROOF_CORPUS_STORE_INTERFACE
    assert store.schema_version == PROOF_CORPUS_STORE_SCHEMA_VERSION
    assert PROOF_CORPUS_STORE_INTERFACE == "ProofCorpusStore@1"
    assert PROOF_CORPUS_ENVELOPE_SCHEMA_VERSION == "proof-corpus-envelope/v1"


def test_artifact_envelope_from_intent_fixture() -> None:
    artifact = _intent_artifact()
    envelope = ArtifactEnvelope.from_intent_artifact(
        artifact, profile=_intent_profile()
    )
    assert envelope.family is ProofCorpusFamily.INTENT
    assert envelope.artifact_cid == artifact.artifact_id
    assert envelope.artifact_digest == artifact.digest
    assert envelope.source_digest == artifact.declaration_digest
    assert envelope.content_cid
    assert envelope.content_digest.startswith("sha256:")
    round_trip = ArtifactEnvelope.from_dict(envelope.to_dict())
    assert round_trip.content_cid == envelope.content_cid
    assert round_trip.content_digest == envelope.content_digest


def test_artifact_envelope_from_legal_fixture() -> None:
    record = _legal_record()
    envelope = ArtifactEnvelope.from_legal_record(record)
    assert envelope.family is ProofCorpusFamily.LEGAL
    assert envelope.profile == record["profile"]
    assert envelope.source_id == record["source_id"]
    assert envelope.source_digest == record["source_digest"]
    assert envelope.jurisdiction == record["jurisdiction"]
    assert envelope.artifact_cid == record["artifact_cid"]
    assert "theorem_receipts" in envelope.attachments or not record.get(
        "theorem_receipts"
    )


def test_artifact_envelope_from_security_fixture() -> None:
    record = _security_record()
    envelope = ArtifactEnvelope.from_security_record(record)
    assert envelope.family is ProofCorpusFamily.SECURITY
    assert envelope.profile == record["profile"]
    assert envelope.source_id == record["declaration_id"]
    assert envelope.source_digest == record["declaration_digest"]
    assert envelope.attachments["declaration_cid"] == record["declaration_cid"]
    assert "security.crypto-exchange" in envelope.attachments[
        "extension_vocabularies"
    ]


def test_unknown_family_fails_closed() -> None:
    with pytest.raises(ProofCorpusSchemaError, match="unknown proof corpus family"):
        ArtifactEnvelope.from_dict(
            {
                "family": "quantum",
                "source_id": "x",
                "source_digest": "sha256:" + "0" * 64,
                "profile": "dev-offline",
                "artifact": {},
            }
        )


def test_family_domain_mismatch_fails_closed() -> None:
    artifact = _intent_artifact()
    with pytest.raises(ProofCorpusIntegrityError, match="does not match"):
        ArtifactEnvelope.build(
            artifact,
            profile="dev-offline",
            family=ProofCorpusFamily.LEGAL,
        )


# ---------------------------------------------------------------------------
# Store accepts three family fixtures
# ---------------------------------------------------------------------------


def test_store_accepts_three_family_fixtures_in_memory() -> None:
    store = ProofCorpusStore()
    intent, legal, security = put_family_fixtures(
        store,
        intent_artifact=_intent_artifact(),
        intent_profile=_intent_profile(),
        legal_record=_legal_record(),
        security_record=_security_record(),
    )

    assert len(store) == 3
    assert set(store.families()) == {"intent", "legal", "security"}

    got_intent = store.get_by_cid(intent.content_cid)
    got_legal = store.get(legal.content_cid)
    got_security = store.get(security.content_cid)

    assert got_intent.family is ProofCorpusFamily.INTENT
    assert got_legal.family is ProofCorpusFamily.LEGAL
    assert got_security.family is ProofCorpusFamily.SECURITY

    assert got_intent.content_digest == intent.content_digest
    assert got_legal.content_digest == legal.content_digest
    assert got_security.content_digest == security.content_digest

    by_family = store.list_by_family(ProofCorpusFamily.LEGAL)
    assert len(by_family) == 1
    assert by_family[0].content_cid == legal.content_cid


def test_store_accepts_three_family_fixtures_on_disk(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus"
    store = ProofCorpusStore(root=root)
    intent, legal, security = _three_envelopes()
    store.put(intent)
    store.put(legal)
    store.put(security)

    reloaded = ProofCorpusStore(root=root)
    assert len(reloaded) == 3
    assert reloaded.contains(intent.content_cid)
    assert reloaded.get(legal.content_cid).family is ProofCorpusFamily.LEGAL
    assert (
        reloaded.get_by_source_digest(
            security.source_digest, profile=security.profile
        ).content_cid
        == security.content_cid
    )
    assert reloaded.get_by_profile(intent.profile).content_cid == intent.content_cid


def test_put_formalization_artifact_directly() -> None:
    store = ProofCorpusStore()
    artifact = _intent_artifact()
    envelope = store.put(artifact, profile=_intent_profile())
    assert envelope.family is ProofCorpusFamily.INTENT
    assert store.get(envelope.content_cid).artifact_cid == artifact.artifact_id


def test_hit_miss_stats() -> None:
    store = ProofCorpusStore()
    intent, _, _ = _three_envelopes()
    store.put(intent)
    store.get(intent.content_cid)
    with pytest.raises(ProofCorpusStoreError, match="not found"):
        store.get("bafkrei" + "a" * 50)
    stats = store.stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["size"] == 1


# ---------------------------------------------------------------------------
# Corruption fails closed
# ---------------------------------------------------------------------------


def test_content_digest_tamper_fails_closed() -> None:
    intent, _, _ = _three_envelopes()
    payload = intent.to_dict()
    payload["content_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ProofCorpusIntegrityError, match="content_digest"):
        ArtifactEnvelope.from_dict(payload)


def test_artifact_payload_tamper_fails_closed() -> None:
    intent, _, _ = _three_envelopes()
    payload = intent.to_dict()
    # Mutate a nested field so recomputed artifact identity drifts.
    payload["artifact"] = dict(payload["artifact"])
    payload["artifact"]["sample_id"] = "tampered-sample-id"
    with pytest.raises(
        (ProofCorpusIntegrityError, ProofCorpusSchemaError)
    ):
        ArtifactEnvelope.from_dict(payload)


def test_on_disk_corruption_fails_closed_on_get(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-corrupt-get"
    store = ProofCorpusStore(root=root)
    intent, _, _ = _three_envelopes()
    store.put(intent)

    path = root / "envelopes" / f"{intent.content_cid}.json"
    assert path.is_file()
    payload = _load_json(path)
    # Corrupt artifact digest while leaving content_cid filename intact.
    payload["artifact_digest"] = "sha256:" + "a" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    # Drop memory cache so get reloads from disk.
    store._envelopes.clear()  # noqa: SLF001 — intentional integrity probe
    with pytest.raises(
        (ProofCorpusStoreIntegrityError, ProofCorpusIntegrityError)
    ):
        store.get(intent.content_cid)


def test_on_disk_corruption_fails_closed_on_reload(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-corrupt-reload"
    store = ProofCorpusStore(root=root)
    intent, legal, security = _three_envelopes()
    store.put(intent)
    store.put(legal)
    store.put(security)

    # Corrupt one envelope body after a successful multi-family put.
    path = root / "envelopes" / f"{legal.content_cid}.json"
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace(legal.profile, "tampered-profile", 1), encoding="utf-8")

    with pytest.raises(
        (ProofCorpusStoreIntegrityError, ProofCorpusIntegrityError)
    ):
        ProofCorpusStore(root=root)


def test_unreadable_envelope_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-unreadable"
    store = ProofCorpusStore(root=root)
    intent, _, _ = _three_envelopes()
    store.put(intent)

    path = root / "envelopes" / f"{intent.content_cid}.json"
    path.write_bytes(b"{not-json")

    store._envelopes.clear()  # noqa: SLF001
    with pytest.raises(ProofCorpusStoreIntegrityError, match="unreadable"):
        store.get(intent.content_cid)


def test_index_references_missing_envelope_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "proof-corpus-index-drift"
    store = ProofCorpusStore(root=root)
    intent, _, _ = _three_envelopes()
    store.put(intent)

    index_path = root / "index.json"
    index = _load_json(index_path)
    index["profiles"][intent.profile] = "bafkreimissingenvelope000000000000000000000000000"
    index_path.write_text(json.dumps(index, sort_keys=True), encoding="utf-8")

    with pytest.raises(
        ProofCorpusStoreIntegrityError, match="missing envelope"
    ):
        ProofCorpusStore(root=root)


def test_intent_attachments_rejected() -> None:
    artifact = _intent_artifact()
    with pytest.raises(ProofCorpusSchemaError, match="must not carry"):
        ArtifactEnvelope.build(
            artifact,
            profile=_intent_profile(),
            family=ProofCorpusFamily.INTENT,
            attachments={"theorem_receipts": []},
        )
