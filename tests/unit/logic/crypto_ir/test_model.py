"""Unit tests for the Crypto IR model, identity, provenance, and schema core.

Covers CRYPTOIR-G020 / CRYPTOIR-003 acceptance:

* records are frozen, strict, round-trippable, mutation resistant, and content
  addressed;
* identity includes chain/genesis and schema profiles;
* amounts reject floats;
* ordering and multiplicity are explicit;
* observations carry finality, completeness, validity, and retraction;
* unknown authoritative extensions fail closed;
* shared ir_core types are reused rather than cloned;
* declarations, observations, assumptions, results, and authorization remain
  separate so conversion cannot elevate authority.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.crypto_ir import (
    AccountIdentity,
    AnalysisResultRef,
    ArtifactKind,
    AssetIdentity,
    AuthorityKind,
    AuthorizationDecisionRef,
    CRYPTO_IR_IDENTITY_DOMAIN,
    CRYPTO_IR_IDENTITY_PROFILE,
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
    CRYPTO_IR_MODEL_SCHEMA,
    CallIntent,
    CanonicalIdentity,
    ChainIdentity,
    CompletenessReceipt,
    CompletenessStatus,
    ContractArtifact,
    CryptoAssumption,
    CryptoExtension,
    CryptoIRValidationError,
    ExactAmount,
    ExpectedEffect,
    FinalityStatus,
    IDENTITY_PROFILE_NAME,
    LedgerCoordinate,
    ObservedTransaction,
    RetractionStatus,
    SCHEMA_VERSIONS,
    SerializedTransactionCandidate,
    SignerRequirement,
    TransferIntent,
    UnsignedTransactionIntent,
    ValidityWindow,
    WalletDescriptor,
    assert_authority_not_elevated,
    crypto_ir_identity,
    get_schema_version,
    observation_provenance,
    record_layer,
    refuse_authority_elevation,
    schema_registry_descriptor,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    IDENTITY_PROFILE as IR_CORE_IDENTITY_PROFILE,
)
from ipfs_datasets_py.logic.ir_core.provenance import (
    Provenance as IRCoreProvenance,
    SourceRef,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


GENESIS = "sha256:" + ("ab" * 32)


def _chain(**overrides: object) -> ChainIdentity:
    payload = {
        "chain_namespace": "eip155",
        "network": "ethereum-mainnet",
        "genesis_digest": GENESIS,
        "chain_id": "1",
        "display_name": "Ethereum Mainnet",
    }
    payload.update(overrides)
    return ChainIdentity(**payload)  # type: ignore[arg-type]


def _account(address: str = "0xabc", **overrides: object) -> AccountIdentity:
    payload = {
        "chain": _chain(),
        "address_normalized": address.lower(),
        "address_original": address,
        "account_kind": "eoa",
    }
    payload.update(overrides)
    return AccountIdentity(**payload)  # type: ignore[arg-type]


def _asset(**overrides: object) -> AssetIdentity:
    payload = {
        "chain": _chain(),
        "asset_namespace": "native",
        "asset_reference": "eth",
        "decimals": 18,
        "symbol": "ETH",
    }
    payload.update(overrides)
    return AssetIdentity(**payload)  # type: ignore[arg-type]


def _intent() -> UnsignedTransactionIntent:
    origin = _account("0xOrigin")
    return UnsignedTransactionIntent(
        intent_id="intent-1",
        chain=_chain(),
        origin=origin,
        signers=(SignerRequirement(account=origin),),
        transfers=(
            TransferIntent(
                asset=_asset(),
                amount=ExactAmount.from_int(1_000_000_000_000_000_000, decimals=18),
                from_account=origin,
                to_account=_account("0xDest"),
            ),
        ),
        calls=(
            CallIntent(
                target=_account("0xContract"),
                method="transfer",
                calldata_digest="sha256:" + ("cd" * 32),
            ),
        ),
        expected_effects=(
            ExpectedEffect(
                effect_id="eff-1",
                kind="transfer",
                summary="send 1 ETH",
            ),
        ),
        assumption_ids=("asm-1",),
        memo="payment",
    )


# ---------------------------------------------------------------------------
# Schema versions
# ---------------------------------------------------------------------------


def test_schema_registry_is_closed_and_deterministic() -> None:
    descriptor = schema_registry_descriptor()
    assert descriptor["registry_schema"].startswith("ipfs-datasets.crypto-ir")
    identifiers = [item["identifier"] for item in descriptor["schemas"]]
    assert identifiers == sorted(identifiers)
    assert CRYPTO_IR_MODEL_SCHEMA.identifier in SCHEMA_VERSIONS
    assert get_schema_version(CRYPTO_IR_MODEL_SCHEMA.identifier) is SCHEMA_VERSIONS[
        CRYPTO_IR_MODEL_SCHEMA.identifier
    ]
    with pytest.raises(Exception):
        get_schema_version("ipfs-datasets.crypto-ir.unknown@9.9.9")


def test_kernel_schema_version_constant() -> None:
    assert CRYPTO_IR_KERNEL_SCHEMA_VERSION == "crypto-ir/v1"


# ---------------------------------------------------------------------------
# Identity reuses ir_core
# ---------------------------------------------------------------------------


def test_identity_profile_reuses_ir_core() -> None:
    assert IDENTITY_PROFILE_NAME == "ir-canonical-identity-v1"
    assert CRYPTO_IR_IDENTITY_PROFILE.identity_profile is IR_CORE_IDENTITY_PROFILE
    assert CRYPTO_IR_IDENTITY_DOMAIN == "crypto-ir"
    descriptor = CRYPTO_IR_IDENTITY_PROFILE.to_dict()
    assert descriptor["identity_profile"]["name"] == IDENTITY_PROFILE_NAME
    assert descriptor["schema_version"] == CRYPTO_IR_KERNEL_SCHEMA_VERSION


def test_chain_identity_content_addressed_and_round_trip() -> None:
    chain = _chain()
    restored = ChainIdentity.from_dict(chain.to_dict())
    assert restored == chain
    identity = chain.identity
    assert isinstance(identity, CanonicalIdentity)
    assert identity.domain.endswith("chain-identity")
    assert identity.cid.startswith("b")
    assert identity.digest.startswith("sha256:")
    # Stable across recomputation.
    assert chain.identity.cid == restored.identity.cid


def test_chain_identity_rejects_unknown_fields() -> None:
    payload = _chain().to_dict()
    payload["extra_authority"] = "nope"
    with pytest.raises(CryptoIRValidationError, match="unknown"):
        ChainIdentity.from_dict(payload)


def test_account_identity_binds_chain_and_original_address() -> None:
    account = _account("0xAbCdEf")
    assert account.address_normalized == "0xabcdef"
    assert account.address_original == "0xAbCdEf"
    assert account.chain.genesis_digest == GENESIS
    assert AccountIdentity.from_dict(account.to_dict()) == account
    assert account.identity.cid == AccountIdentity.from_dict(account.to_dict()).identity.cid


# ---------------------------------------------------------------------------
# Exact amounts reject floats
# ---------------------------------------------------------------------------


def test_exact_amount_accepts_integer_strings() -> None:
    amount = ExactAmount(base_units="1000", decimals=3)
    assert amount.to_dict() == {"base_units": "1000", "decimals": 3}
    assert ExactAmount.from_dict(amount.to_dict()) == amount
    assert ExactAmount.from_int(42, decimals=0).base_units == "42"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_units": 1.5, "decimals": 0},
        {"base_units": "1.5", "decimals": 0},
        {"base_units": "01", "decimals": 0},
        {"base_units": "1e3", "decimals": 0},
    ],
)
def test_exact_amount_rejects_floats_and_noncanonical(kwargs: dict) -> None:
    with pytest.raises(CryptoIRValidationError):
        ExactAmount(**kwargs)


def test_exact_amount_from_int_rejects_float_and_bool() -> None:
    with pytest.raises(CryptoIRValidationError):
        ExactAmount.from_int(1.0, decimals=0)  # type: ignore[arg-type]
    with pytest.raises(CryptoIRValidationError):
        ExactAmount.from_int(True, decimals=0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Frozen / mutation resistant
# ---------------------------------------------------------------------------


def test_records_are_frozen_and_mutation_resistant() -> None:
    chain = _chain()
    with pytest.raises(dataclasses.FrozenInstanceError):
        chain.network = "other"  # type: ignore[misc]
    account = _account()
    with pytest.raises(TypeError):
        account.attributes["x"] = 1  # type: ignore[index]
    assert isinstance(account.attributes, MappingProxyType)


# ---------------------------------------------------------------------------
# Unsigned intent + serialized candidate
# ---------------------------------------------------------------------------


def test_unsigned_intent_round_trip_and_ordered_signers() -> None:
    intent = _intent()
    restored = UnsignedTransactionIntent.from_dict(intent.to_dict())
    assert restored == intent
    assert restored.identity.cid == intent.identity.cid
    assert record_layer(intent) is AuthorityKind.DECLARATION
    # Ordering of signers/transfers is preserved (ordered collections).
    assert [s.account.address_normalized for s in restored.signers] == [
        s.account.address_normalized for s in intent.signers
    ]


def test_unsigned_intent_requires_signer() -> None:
    origin = _account()
    with pytest.raises(CryptoIRValidationError, match="signer"):
        UnsignedTransactionIntent(
            intent_id="x",
            chain=_chain(),
            origin=origin,
            signers=(),
        )


def test_serialized_candidate_binds_intent_and_payload() -> None:
    candidate = SerializedTransactionCandidate(
        candidate_id="cand-1",
        intent_id="intent-1",
        chain=_chain(),
        payload_digest="aa" * 32,
        encoding="rlp",
        byte_length=120,
    )
    assert candidate.payload_digest.startswith("sha256:")
    assert SerializedTransactionCandidate.from_dict(candidate.to_dict()) == candidate
    assert record_layer(candidate) is AuthorityKind.DECLARATION
    assert candidate.identity.cid.startswith("b")


# ---------------------------------------------------------------------------
# Contract artifact
# ---------------------------------------------------------------------------


def test_contract_artifact_round_trip() -> None:
    artifact = ContractArtifact(
        artifact_id="art-1",
        chain=_chain(),
        kind=ArtifactKind.BYTECODE,
        content_digest="bb" * 32,
        media_type="application/octet-stream",
        byte_length=2048,
        content_cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
        label="runtime",
    )
    restored = ContractArtifact.from_dict(artifact.to_dict())
    assert restored == artifact
    assert restored.kind is ArtifactKind.BYTECODE
    assert restored.identity.digest == artifact.identity.digest


# ---------------------------------------------------------------------------
# Observations + completeness
# ---------------------------------------------------------------------------


def test_observed_transaction_carries_finality_validity_retraction() -> None:
    prov = observation_provenance(
        producer_id="wallet-adapter-evm",
        observed_at="2026-07-29T00:00:00Z",
        finality=FinalityStatus.FINALIZED,
        validity_start="2026-07-29T00:00:00Z",
        validity_end="2026-07-30T00:00:00Z",
        retraction_status=RetractionStatus.NOT_RETRACTED,
        reorg_depth=0,
    )
    obs = ObservedTransaction(
        observation_id="obs-1",
        chain=_chain(),
        tx_digest="cc" * 32,
        coordinate=LedgerCoordinate(sequence=12_000_000, hash="0xblock"),
        finality=FinalityStatus.FINALIZED,
        retraction=RetractionStatus.NOT_RETRACTED,
        validity=ValidityWindow(
            start="2026-07-29T00:00:00Z", end="2026-07-30T00:00:00Z"
        ),
        from_account=_account("0xfrom"),
        to_account=_account("0xto"),
        provenance=prov,
    )
    restored = ObservedTransaction.from_dict(obs.to_dict())
    assert restored.finality is FinalityStatus.FINALIZED
    assert restored.retraction is RetractionStatus.NOT_RETRACTED
    assert restored.validity.start == "2026-07-29T00:00:00Z"
    assert restored.provenance is not None
    assert restored.provenance.authority.kind is AuthorityKind.OBSERVATION
    assert record_layer(obs) is AuthorityKind.OBSERVATION


def test_completeness_receipt_round_trip_and_identity() -> None:
    receipt = CompletenessReceipt(
        receipt_id="cmp-1",
        chain=_chain(),
        scope="account-history:0xabc",
        completeness=CompletenessStatus.PARTIAL,
        finality=FinalityStatus.CONFIRMED,
        validity=ValidityWindow(start="2026-01-01T00:00:00Z", end="2026-07-29T00:00:00Z"),
        retraction=RetractionStatus.NOT_RETRACTED,
        covered_ranges=(LedgerCoordinate(sequence=1), LedgerCoordinate(sequence=100)),
        missing_ranges=(LedgerCoordinate(sequence=101),),
        provider_ids=("rpc-a", "rpc-b"),
        assumption_ids=("asm-provider-honest",),
        provenance=observation_provenance(
            producer_id="completeness-scanner",
            observed_at="2026-07-29T12:00:00Z",
            finality=FinalityStatus.CONFIRMED,
        ),
    )
    restored = CompletenessReceipt.from_dict(receipt.to_dict())
    assert restored == receipt
    assert restored.completeness is CompletenessStatus.PARTIAL
    assert restored.finality is FinalityStatus.CONFIRMED
    assert restored.identity.cid == receipt.identity.cid
    assert record_layer(receipt) is AuthorityKind.OBSERVATION


def test_unknown_required_extension_fails_closed() -> None:
    with pytest.raises(CryptoIRValidationError, match="fails closed"):
        CompletenessReceipt(
            receipt_id="cmp-2",
            chain=_chain(),
            scope="x",
            completeness=CompletenessStatus.COMPLETE,
            finality=FinalityStatus.FINALIZED,
            validity=ValidityWindow(),
            retraction=RetractionStatus.NOT_RETRACTED,
            extensions=(
                CryptoExtension(
                    extension_id="ext-1",
                    vocabulary="unknown.vocab",
                    version="1.0.0",
                    payload={"k": "v"},
                    required=True,
                ),
            ),
            accepted_extension_vocabularies=(),
        )


def test_known_required_extension_is_accepted() -> None:
    receipt = CompletenessReceipt(
        receipt_id="cmp-3",
        chain=_chain(),
        scope="x",
        completeness=CompletenessStatus.COMPLETE,
        finality=FinalityStatus.FINALIZED,
        validity=ValidityWindow(),
        retraction=RetractionStatus.NOT_RETRACTED,
        extensions=(
            CryptoExtension(
                extension_id="ext-1",
                vocabulary="crypto-ir.experimental",
                version="1.0.0",
                payload={"ok": True},
                required=True,
            ),
        ),
        accepted_extension_vocabularies=("crypto-ir.experimental",),
    )
    assert len(receipt.extensions) == 1


# ---------------------------------------------------------------------------
# Authority separation
# ---------------------------------------------------------------------------


def test_authority_layers_are_distinct() -> None:
    assert record_layer(_chain()) is AuthorityKind.DECLARATION
    assert record_layer(_intent()) is AuthorityKind.DECLARATION
    assert (
        record_layer(
            CryptoAssumption(assumption_id="a1", statement="provider is honest")
        )
        is AuthorityKind.ASSUMPTION
    )
    assert (
        record_layer(
            AnalysisResultRef(
                result_id="r1",
                kind="proof",
                subject_identity="cid:x",
                outcome="PROVED",
            )
        )
        is AuthorityKind.RESULT
    )
    assert (
        record_layer(
            AuthorizationDecisionRef(
                decision_id="d1",
                candidate_id="cand-1",
                verdict="ALLOW",
                policy_id="policy-v1",
            )
        )
        is AuthorityKind.AUTHORIZATION
    )


def test_conversion_cannot_elevate_observation_to_authorization() -> None:
    obs = ObservedTransaction(
        observation_id="obs-2",
        chain=_chain(),
        tx_digest="dd" * 32,
        coordinate=LedgerCoordinate(sequence=1),
        finality=FinalityStatus.CONFIRMED,
        retraction=RetractionStatus.NOT_RETRACTED,
        validity=ValidityWindow(),
    )
    with pytest.raises(CryptoIRValidationError, match="authorization"):
        refuse_authority_elevation(obs, AuthorityKind.AUTHORIZATION)
    with pytest.raises(Exception, match="authorization|elevate"):
        assert_authority_not_elevated(
            AuthorityKind.OBSERVATION, AuthorityKind.AUTHORIZATION
        )


def test_conversion_cannot_rewrite_result_as_authorization() -> None:
    result = AnalysisResultRef(
        result_id="r2",
        kind="heuristic",
        subject_identity="cid:y",
        outcome="UNKNOWN",
    )
    with pytest.raises(CryptoIRValidationError):
        refuse_authority_elevation(result, AuthorityKind.AUTHORIZATION)


def test_declaration_cannot_become_observation_by_conversion() -> None:
    with pytest.raises(Exception):
        assert_authority_not_elevated(
            AuthorityKind.DECLARATION, AuthorityKind.OBSERVATION
        )


# ---------------------------------------------------------------------------
# Wallet + asset helpers
# ---------------------------------------------------------------------------


def test_wallet_descriptor_requires_accounts() -> None:
    with pytest.raises(CryptoIRValidationError, match="account"):
        WalletDescriptor(wallet_id="w1", accounts=())
    wallet = WalletDescriptor(wallet_id="w1", accounts=(_account(),), label="primary")
    assert WalletDescriptor.from_dict(wallet.to_dict()) == wallet


def test_asset_identity_round_trip() -> None:
    asset = _asset()
    assert AssetIdentity.from_dict(asset.to_dict()) == asset


# ---------------------------------------------------------------------------
# Shared ir_core provenance reuse
# ---------------------------------------------------------------------------


def test_shared_ir_core_provenance_is_reusable() -> None:
    from ipfs_datasets_py.logic.crypto_ir.provenance import bind_shared_provenance

    shared = IRCoreProvenance(
        provenance_id="prov-1",
        sources=(
            SourceRef(
                ref_id="src-1",
                source_uri="ipfs://bafy",
                source_id="artifact-1",
                source_revision="1",
                content_sha256="ee" * 32,
            ),
        ),
    )
    digest = bind_shared_provenance(shared)
    assert digest.startswith("sha256:")


def test_crypto_ir_identity_helper_uses_domain() -> None:
    identity = crypto_ir_identity({"hello": "world"})
    assert identity.domain == CRYPTO_IR_IDENTITY_DOMAIN
    assert identity.schema_version == CRYPTO_IR_KERNEL_SCHEMA_VERSION


def test_package_exports_ast_symbols() -> None:
    """AST symbols required by the objective scan are importable."""

    from ipfs_datasets_py.logic import crypto_ir

    for name in (
        "ChainIdentity",
        "AccountIdentity",
        "UnsignedTransactionIntent",
        "SerializedTransactionCandidate",
        "ContractArtifact",
        "CompletenessReceipt",
    ):
        assert hasattr(crypto_ir, name)
        assert getattr(crypto_ir, name) is not None


def test_golden_chain_identity_canonical_bytes_stable() -> None:
    chain = ChainIdentity(
        chain_namespace="eip155",
        network="ethereum-mainnet",
        genesis_digest=GENESIS,
        chain_id="1",
        display_name="Ethereum Mainnet",
    )
    first = chain.canonical_bytes()
    second = ChainIdentity.from_dict(chain.to_dict()).canonical_bytes()
    assert first == second
    assert b"eip155" in first
    assert b"ethereum-mainnet" in first
