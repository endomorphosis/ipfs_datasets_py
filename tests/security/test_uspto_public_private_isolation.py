"""Adversarial isolation tests: private USPTO material never reaches public sinks.

Proves private bytes, text, embeddings, and CIDs cannot enter public IPFS,
public datasets, caches, prompts, logs, or telemetry. Also proves the
credentials vault is not used as a document vault.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
    build_artifact_manifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
    DisclosureClassification,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    SinkDecisionCode,
    UsptoPrivacyPolicy,
    VaultDecisionCode,
    VaultKind,
    deny_private_to_public_sinks,
)

DIGEST = "c" * 64
# Synthetic canaries — not live secrets or real matter content.
PRIVATE_BYTES_CANARY = b"%PDF-PRIVATE-OFFICE-ACTION-SYNTHETIC%"
PRIVATE_TEXT_CANARY = "CONFIDENTIAL unpublished claim language canary-text-9f3a"
PRIVATE_EMBEDDING_CANARY = [0.001, 0.002, 0.003, 0.999]
PRIVATE_CID_CANARY = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CREDENTIAL_CANARY = "vault-ref-not-a-real-secret://uspto/odp-api-token"


PRIVATE_CLASSES = (
    DisclosureClassification.CONFIDENTIAL_APPLICATION,
    DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
    DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
)

PUBLIC_SINKS = tuple(PublicSink)
SUBSTANTIVE_KINDS = (
    ContentKind.DOCUMENT_BYTES,
    ContentKind.EXTRACTED_TEXT,
    ContentKind.EMBEDDING,
    ContentKind.CONTENT_IDENTIFIER,
)


class FakePublicSinkBus:
    """In-memory capture of attempts to publish to public surfaces."""

    def __init__(self, policy: UsptoPrivacyPolicy | None = None) -> None:
        self.policy = policy or UsptoPrivacyPolicy()
        self.accepted: list[dict[str, Any]] = []
        self.denied: list[dict[str, Any]] = []
        self.log_lines: list[str] = []
        self.telemetry_events: list[dict[str, Any]] = []
        self.prompt_payloads: list[Any] = []
        self.ipfs_pins: list[str] = []
        self.dataset_rows: list[Any] = []
        self.cache_entries: list[Any] = []

    def publish(
        self,
        *,
        classification: DisclosureClassification | str,
        sink: PublicSink,
        content_kind: ContentKind,
        payload: Any,
    ) -> bool:
        decision = self.policy.evaluate_sink(classification, sink, content_kind)
        record = {
            "decision": decision.to_dict(),
            "payload_type": type(payload).__name__,
        }
        if not decision.allowed:
            self.denied.append(record)
            # Audit may record reason codes only — never the private payload.
            self.log_lines.append(
                json.dumps(
                    {
                        "event": "sink_denied",
                        "code": decision.code.value,
                        "sink": sink.value,
                        "content_kind": content_kind.value,
                        "classification": decision.classification.value,
                    },
                    sort_keys=True,
                )
            )
            return False

        self.accepted.append(record)
        if sink is PublicSink.PUBLIC_IPFS:
            if content_kind is ContentKind.CONTENT_IDENTIFIER:
                self.ipfs_pins.append(str(payload))
            else:
                self.ipfs_pins.append(f"blob:{type(payload).__name__}")
        elif sink is PublicSink.PUBLIC_DATASET:
            self.dataset_rows.append(payload)
        elif sink is PublicSink.PUBLIC_CACHE:
            self.cache_entries.append(payload)
        elif sink is PublicSink.REMOTE_PROMPT:
            self.prompt_payloads.append(payload)
        elif sink is PublicSink.LOGS:
            self.log_lines.append(str(payload))
        elif sink is PublicSink.TELEMETRY:
            self.telemetry_events.append({"payload": payload})
        elif sink is PublicSink.JUSTICE_DAO:
            self.dataset_rows.append(payload)
        return True


class FakeVault:
    """Separated credentials vs document vaults for isolation proofs."""

    def __init__(self, policy: UsptoPrivacyPolicy | None = None) -> None:
        self.policy = policy or UsptoPrivacyPolicy()
        self.credentials: dict[str, Any] = {}
        self.documents: dict[str, Any] = {}

    def store(
        self,
        vault: VaultKind,
        content_kind: ContentKind,
        classification: DisclosureClassification | str,
        key: str,
        value: Any,
    ) -> None:
        decision = self.policy.evaluate_vault(vault, content_kind, classification)
        if not decision.allowed:
            raise PrivacyBoundaryError(
                decision.reason,
                code=decision.code.value,
                classification=decision.classification.value,
                content_kind=decision.content_kind.value,
                vault=decision.vault.value,
            )
        if vault is VaultKind.CREDENTIALS:
            self.credentials[key] = value
        else:
            self.documents[key] = value


@pytest.fixture
def policy() -> UsptoPrivacyPolicy:
    return UsptoPrivacyPolicy()


@pytest.fixture
def private_manifest() -> ArtifactManifest:
    return build_artifact_manifest(
        artifact_id="artifact:private:iso:1",
        sha256=DIGEST,
        size_bytes=len(PRIVATE_BYTES_CANARY),
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        media_type="application/pdf",
        private_cid=PRIVATE_CID_CANARY,
        matter_id="matter:iso:1",
        encryption_namespace="private://tenant/iso/uspto",
    )


def test_private_bytes_text_embeddings_cids_denied_from_all_public_sinks(
    policy: UsptoPrivacyPolicy,
) -> None:
    bus = FakePublicSinkBus(policy)
    payloads = {
        ContentKind.DOCUMENT_BYTES: PRIVATE_BYTES_CANARY,
        ContentKind.EXTRACTED_TEXT: PRIVATE_TEXT_CANARY,
        ContentKind.EMBEDDING: PRIVATE_EMBEDDING_CANARY,
        ContentKind.CONTENT_IDENTIFIER: PRIVATE_CID_CANARY,
    }
    for cls in PRIVATE_CLASSES:
        for sink in PUBLIC_SINKS:
            for kind, payload in payloads.items():
                ok = bus.publish(
                    classification=cls,
                    sink=sink,
                    content_kind=kind,
                    payload=payload,
                )
                assert ok is False

    assert bus.accepted == []
    assert len(bus.denied) == len(PRIVATE_CLASSES) * len(PUBLIC_SINKS) * len(payloads)
    # Prove canaries never landed in any public surface.
    surface = "\n".join(
        [
            *bus.log_lines,
            json.dumps(bus.telemetry_events, default=str),
            json.dumps(bus.prompt_payloads, default=str),
            json.dumps(bus.ipfs_pins, default=str),
            json.dumps(bus.dataset_rows, default=str),
            json.dumps(bus.cache_entries, default=str),
        ]
    )
    assert PRIVATE_TEXT_CANARY not in surface
    assert PRIVATE_CID_CANARY not in surface
    assert PRIVATE_BYTES_CANARY.decode("latin-1") not in surface
    assert "0.999" not in surface  # embedding canary value


def test_deny_private_to_public_sinks_helper_covers_matrix(
    policy: UsptoPrivacyPolicy,
) -> None:
    denials = deny_private_to_public_sinks(
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        policy=policy,
    )
    assert denials
    assert all(not d.allowed for d in denials)
    # Every sink × substantive kind pair denied.
    pairs = {(d.sink, d.content_kind) for d in denials}
    for sink in PublicSink:
        for kind in SUBSTANTIVE_KINDS:
            assert (sink, kind) in pairs


def test_unknown_classification_quarantines_and_blocks_dispatch(
    policy: UsptoPrivacyPolicy,
) -> None:
    assert policy.must_quarantine(DisclosureClassification.UNKNOWN)
    assert policy.must_quarantine(None)
    assert policy.must_quarantine("totally-unknown-label")

    q = policy.quarantine(
        quarantine_id="q:iso:1",
        classification=None,
        reason_codes=("unknown_classification",),
        content_kinds=SUBSTANTIVE_KINDS,
    )
    assert q.classification is DisclosureClassification.UNKNOWN

    bus = FakePublicSinkBus(policy)
    for sink in PUBLIC_SINKS:
        for kind in SUBSTANTIVE_KINDS:
            assert (
                bus.publish(
                    classification=DisclosureClassification.UNKNOWN,
                    sink=sink,
                    content_kind=kind,
                    payload=PRIVATE_TEXT_CANARY,
                )
                is False
            )
    assert bus.accepted == []
    assert all(
        d["decision"]["code"] == SinkDecisionCode.DENIED_QUARANTINE.value
        for d in bus.denied
    )


def test_assert_sink_allowed_raises_without_leaking_payload(
    policy: UsptoPrivacyPolicy,
) -> None:
    with pytest.raises(PrivacyBoundaryError) as caught:
        policy.assert_sink_allowed(
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
            PublicSink.PUBLIC_IPFS,
            ContentKind.EXTRACTED_TEXT,
        )
    err = caught.value
    rendered = f"{err!s}\n{err!r}\n{json.dumps(err.audit_dict())}"
    assert PRIVATE_TEXT_CANARY not in rendered
    assert err.code == SinkDecisionCode.DENIED_PRIVATE.value
    assert "matched" not in rendered.lower() or "private" in err.reason.lower()
    audit = err.audit_dict()
    assert audit["sink"] == PublicSink.PUBLIC_IPFS.value
    assert "text" not in audit


def test_private_cid_never_announced_to_public_ipfs(
    private_manifest: ArtifactManifest, policy: UsptoPrivacyPolicy
) -> None:
    denials = private_manifest.private_cid_public_sink_denials(policy=policy)
    assert denials
    assert all(not d["allowed"] for d in denials)
    sinks = {d["sink"] for d in denials}
    assert PublicSink.PUBLIC_IPFS.value in sinks
    assert PublicSink.PUBLIC_DATASET.value in sinks
    assert PublicSink.PUBLIC_CACHE.value in sinks
    assert PublicSink.TELEMETRY.value in sinks
    assert PublicSink.LOGS.value in sinks
    assert PublicSink.REMOTE_PROMPT.value in sinks

    bus = FakePublicSinkBus(policy)
    assert (
        bus.publish(
            classification=private_manifest.classification,
            sink=PublicSink.PUBLIC_IPFS,
            content_kind=ContentKind.CONTENT_IDENTIFIER,
            payload=private_manifest.private_cid,
        )
        is False
    )
    assert bus.ipfs_pins == []
    assert private_manifest.public_cid is None
    # Public projection must not expose private CID.
    projection = private_manifest.public_projection()
    assert "private_cid" not in projection
    assert PRIVATE_CID_CANARY not in json.dumps(projection)


def test_external_prompts_denied_for_private_by_default(
    policy: UsptoPrivacyPolicy,
) -> None:
    bus = FakePublicSinkBus(policy)
    for kind, payload in (
        (ContentKind.EXTRACTED_TEXT, PRIVATE_TEXT_CANARY),
        (ContentKind.DOCUMENT_BYTES, PRIVATE_BYTES_CANARY),
        (ContentKind.EMBEDDING, PRIVATE_EMBEDDING_CANARY),
        (ContentKind.CONTENT_IDENTIFIER, PRIVATE_CID_CANARY),
    ):
        assert (
            bus.publish(
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
                sink=PublicSink.REMOTE_PROMPT,
                content_kind=kind,
                payload=payload,
            )
            is False
        )
    assert bus.prompt_payloads == []


def test_logs_and_telemetry_redact_private_substance(
    policy: UsptoPrivacyPolicy,
) -> None:
    payload = {
        "artifact_id": "artifact:private:iso:1",
        "matter_id": "matter:iso:1",
        "classification": DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
        "digest": DIGEST,
        "text": PRIVATE_TEXT_CANARY,
        "embedding": PRIVATE_EMBEDDING_CANARY,
        "cid": PRIVATE_CID_CANARY,
        "bytes": PRIVATE_BYTES_CANARY.hex(),
        "prompt": PRIVATE_TEXT_CANARY,
    }
    redacted = policy.redact_for_logs(
        DisclosureClassification.CONFIDENTIAL_APPLICATION, payload
    )
    rendered = canonical_json(dict(redacted))
    assert PRIVATE_TEXT_CANARY not in rendered
    assert PRIVATE_CID_CANARY not in rendered
    assert PRIVATE_BYTES_CANARY.hex() not in rendered
    assert "0.999" not in rendered
    assert redacted["artifact_id"] == "artifact:private:iso:1"
    assert redacted["redacted"] is True

    # Quarantined unknown also redacts.
    unknown_redacted = policy.redact_for_logs(
        DisclosureClassification.UNKNOWN, payload
    )
    unknown_rendered = canonical_json(dict(unknown_redacted))
    assert PRIVATE_TEXT_CANARY not in unknown_rendered
    assert PRIVATE_CID_CANARY not in unknown_rendered


def test_credentials_vault_is_not_document_vault(policy: UsptoPrivacyPolicy) -> None:
    vault = FakeVault(policy)

    # Documents cannot enter credentials vault.
    for kind, value in (
        (ContentKind.DOCUMENT_BYTES, PRIVATE_BYTES_CANARY),
        (ContentKind.EXTRACTED_TEXT, PRIVATE_TEXT_CANARY),
        (ContentKind.EMBEDDING, PRIVATE_EMBEDDING_CANARY),
        (ContentKind.CONTENT_IDENTIFIER, PRIVATE_CID_CANARY),
    ):
        with pytest.raises(PrivacyBoundaryError) as caught:
            vault.store(
                VaultKind.CREDENTIALS,
                kind,
                DisclosureClassification.CONFIDENTIAL_APPLICATION,
                key=f"doc-{kind.value}",
                value=value,
            )
        assert (
            caught.value.code
            == VaultDecisionCode.DENIED_CREDENTIALS_AS_DOCUMENT.value
        )

    assert vault.credentials == {}

    # Credentials cannot enter document vault.
    with pytest.raises(PrivacyBoundaryError) as caught:
        vault.store(
            VaultKind.DOCUMENT,
            ContentKind.CREDENTIAL_SECRET,
            DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            key="api-token",
            value=CREDENTIAL_CANARY,
        )
    assert caught.value.code == VaultDecisionCode.DENIED_DOCUMENT_AS_CREDENTIAL.value
    assert vault.documents == {}

    # Happy paths: secrets → credentials vault; document bytes → document vault.
    vault.store(
        VaultKind.CREDENTIALS,
        ContentKind.CREDENTIAL_SECRET,
        DisclosureClassification.CREDENTIAL_OR_PAYMENT,
        key="api-token",
        value=CREDENTIAL_CANARY,
    )
    vault.store(
        VaultKind.DOCUMENT,
        ContentKind.DOCUMENT_BYTES,
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        key="oa-pdf",
        value=PRIVATE_BYTES_CANARY,
    )
    assert vault.credentials["api-token"] == CREDENTIAL_CANARY
    assert vault.documents["oa-pdf"] == PRIVATE_BYTES_CANARY
    # Cross-contamination must not occur.
    assert PRIVATE_BYTES_CANARY not in vault.credentials.values()
    assert CREDENTIAL_CANARY not in vault.documents.values()


def test_credential_classification_cannot_become_artifact_manifest(
    policy: UsptoPrivacyPolicy,
) -> None:
    with pytest.raises(PrivacyBoundaryError):
        build_artifact_manifest(
            artifact_id="artifact:cred:iso",
            sha256=DIGEST,
            size_bytes=16,
            classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            policy=policy,
        )
    with pytest.raises(ValueError, match="credential_or_payment"):
        ArtifactManifest(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            artifact_id="artifact:cred:iso2",
            sha256=DIGEST,
            size_bytes=16,
            classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            media_type="text/plain",
            media_signature=None,
            private_cid=None,
            public_cid=None,
            encryption_namespace="private://x",
            matter_id=None,
            source_receipt_id=None,
            authority_relation=AuthorityRelation.UNKNOWN,
            parent_artifact_ids=(),
            parser_versions={},
            labels={},
        )


def test_export_review_denied_from_public_sinks(policy: UsptoPrivacyPolicy) -> None:
    denials = deny_private_to_public_sinks(
        DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        policy=policy,
    )
    assert denials
    assert all(
        d.code
        in (
            SinkDecisionCode.DENIED_EXPORT_REVIEW,
            SinkDecisionCode.DENIED_PRIVATE,
        )
        for d in denials
    )


def test_public_official_may_use_public_sinks_for_non_secrets(
    policy: UsptoPrivacyPolicy,
) -> None:
    bus = FakePublicSinkBus(policy)
    assert (
        bus.publish(
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            sink=PublicSink.PUBLIC_DATASET,
            content_kind=ContentKind.METADATA_DIGEST,
            payload={"sha256": DIGEST},
        )
        is True
    )
    # Secrets still blocked even under public classification.
    assert (
        bus.publish(
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            sink=PublicSink.PUBLIC_IPFS,
            content_kind=ContentKind.CREDENTIAL_SECRET,
            payload=CREDENTIAL_CANARY,
        )
        is False
    )


def test_manifest_assert_document_vault_only(
    private_manifest: ArtifactManifest, policy: UsptoPrivacyPolicy
) -> None:
    private_manifest.assert_document_vault_only(policy=policy)
    # Direct credentials-vault check remains denied.
    decision = policy.evaluate_vault(
        VaultKind.CREDENTIALS,
        ContentKind.DOCUMENT_BYTES,
        private_manifest.classification,
    )
    assert decision.allowed is False
    assert decision.code is VaultDecisionCode.DENIED_CREDENTIALS_AS_DOCUMENT


def test_mixed_bundle_inherits_private_and_blocks_public_ipfs(
    policy: UsptoPrivacyPolicy,
) -> None:
    effective = policy.classify_before_dispatch(
        DisclosureClassification.PUBLIC_OFFICIAL,
        source_classifications=(
            DisclosureClassification.PUBLIC_USER,
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        ),
    )
    assert effective is DisclosureClassification.PRIVILEGED_WORK_PRODUCT
    decision = policy.evaluate_sink(
        effective, PublicSink.PUBLIC_IPFS, ContentKind.DOCUMENT_BYTES
    )
    assert decision.allowed is False
