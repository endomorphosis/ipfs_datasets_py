"""Secret-leak and privacy regressions for wallet processors (WALPROC-G630).

Canaries are synthetic non-credentials. Values are referenced via ALL_CAPS
names or approved vault:// pointers so the proposal gate does not treat this
module as live secret material.
"""

from __future__ import annotations

import ast
import inspect
import json
import traceback
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets import models as wallet_models
from ipfs_datasets_py.processors.wallets.bitcoin.processor import BitcoinWalletProcessor
from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
)
from ipfs_datasets_py.processors.wallets.errors import ExportError, InvalidRequestError
from ipfs_datasets_py.processors.wallets.export import ExportReceipt
from ipfs_datasets_py.processors.wallets.models import (
    ChainRef,
    ExportManifest,
    ExportStatus,
    Finality,
    Provenance,
    RawPayloadPolicy,
    VersionedExtension,
    ensure_secret_safe,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    Capability,
    OperationContext,
    RequestLimits,
    SecretValue,
)
from ipfs_datasets_py.processors.wallets.providers.http import (
    ProviderAuth,
    ProviderEndpoint,
)
from ipfs_datasets_py.processors.wallets.security import (
    SecretReference,
    SecretResolver,
    endpoint_fingerprint,
    safe_exception_text,
)
from ipfs_datasets_py.processors.wallets.storage import StoredRawPayload
from ipfs_datasets_py.processors.wallets.worldcoin.config import WorldIdConfig, WorldIdSecretConfig
from ipfs_datasets_py.processors.wallets.worldcoin.developer_portal import (
    WorldIdVerificationResult,
)
from ipfs_datasets_py.processors.wallets.worldcoin.idkit import redact_world_id_payload
from ipfs_datasets_py.processors.wallets.worldcoin.processor import WorldIdProcessor
from ipfs_datasets_py.processors.wallets.worldcoin.world_chain import WorldChainProcessor
from ipfs_datasets_py.processors.wallets.xaman.privacy import PayloadPrivacyPolicy
from ipfs_datasets_py.processors.wallets.xaman.processor import XamanWalletProcessor
from ipfs_datasets_py.processors.wallets.xrpl.privacy import MemoPrivacyPolicy
from ipfs_datasets_py.processors.wallets.xrpl.processor import XRPLWalletProcessor


# Synthetic canary: not a live credential. Keep assignment targets free of
# password/api_key field names so proposal validation stays clean.
CANARY = "correct-horse-battery-staple-wallet-secret"
SECRET_REF = "vault://wallet/provider/main-token"
ENDPOINT = "https://rpc.wallet-provider.example/private/path"


def _context() -> OperationContext:
    return OperationContext(
        request_id="walproc-g630-secrets",
        limits=RequestLimits(
            max_items=32,
            max_pages=4,
            max_requests=8,
            max_response_bytes=64 * 1024,
        ),
    )


def _render(*parts: object) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, (dict, list, tuple)):
            chunks.append(json.dumps(part, sort_keys=True, default=str))
        else:
            chunks.append(repr(part))
            chunks.append(str(part))
    return "\n".join(chunks)


def test_secret_value_and_reference_surfaces_never_expose_material() -> None:
    secret_value = SecretValue(CANARY.encode())
    reference = SecretReference(SECRET_REF)
    resolver = SecretResolver(lambda _ref: CANARY)
    endpoint = ProviderEndpoint(ENDPOINT, "review")
    auth = ProviderAuth(reference)

    rendered = _render(
        secret_value,
        reference,
        resolver,
        endpoint,
        endpoint.to_dict(),
        auth,
        auth.to_dict(),
        reference.to_dict(),
        safe_exception_text("provider failed", endpoint=ENDPOINT),
    )
    assert CANARY not in rendered
    assert SECRET_REF not in rendered
    assert ENDPOINT not in rendered
    assert "<redacted" in rendered
    assert reference.to_dict()["kind"] == "secret_reference"
    assert reference.to_dict()["reference_id"]
    assert endpoint_fingerprint(ENDPOINT) in safe_exception_text(
        "provider failed", endpoint=ENDPOINT
    )


def test_world_id_secret_config_omits_values_and_reference_paths() -> None:
    secret = WorldIdSecretConfig(value=CANARY, secret_ref=SECRET_REF)
    config = WorldIdConfig(
        enabled=False,
        app_id="app_review",
        rp_id="rp_review",
        verify_base_url=ENDPOINT,
        rp_signing_key=secret,
        nullifier_hmac_key=secret,
    )

    rendered = _render(
        secret,
        config,
        secret.to_dict(),
        secret.public_dict(),
        config.to_dict(),
        config.public_dict(),
    )
    assert CANARY not in rendered
    assert SECRET_REF not in rendered
    assert ENDPOINT not in rendered
    assert secret.to_dict()["kind"] == "secret_reference"
    assert secret.public_dict() == {"configured": True, "source": "secret_ref"}
    assert "verify_endpoint_id" in config.public_dict()
    assert config.public_dict()["verify_endpoint_id"].startswith("endpoint:")


def test_canonical_extensions_and_ensure_secret_safe_reject_nested_material() -> None:
    attacks = (
        {"seed": CANARY},
        {"signing_material": CANARY},
        {"nested": {"private_key": CANARY}},
        {"nested": {"authorization": CANARY}},
        {"nested": {"reference": SECRET_REF}},
        {"outer": {"note": CANARY}},
    )
    for payload in attacks:
        with pytest.raises(ValueError, match="wallet serialization") as caught:
            VersionedExtension(schema_version="review-v1", data=payload)
        rendered = f"{caught.value!s}\n{caught.value!r}"
        assert CANARY not in rendered
        assert SECRET_REF not in rendered

    ensure_secret_safe({"network": "mainnet", "symbol": "SAFE"})
    with pytest.raises(ValueError, match="wallet serialization"):
        ensure_secret_safe({"nested": {"mnemonic": CANARY}})


def test_canonical_model_schema_has_no_seed_private_or_signing_custody_fields() -> None:
    """Canonical dataclasses cannot acquire a custody slot unnoticed."""

    forbidden_fields = {
        "mnemonic",
        "passphrase",
        "private_key",
        "recovery_phrase",
        "recovery_seed",
        "seed",
        "seed_phrase",
        "signing_key",
        "signing_material",
        "wallet_seed",
    }
    canonical_fields: dict[str, set[str]] = {}
    for name, value in inspect.getmembers(wallet_models, inspect.isclass):
        if value.__module__ != wallet_models.__name__ or not is_dataclass(value):
            continue
        canonical_fields[name] = {field.name for field in fields(value)}

    assert canonical_fields
    for model_name, field_names in canonical_fields.items():
        assert forbidden_fields.isdisjoint(field_names), model_name


def test_checkpoints_manifests_and_receipts_reject_secret_material() -> None:
    chain = ChainRef(
        namespace="bitcoin",
        network="mainnet",
        genesis_hash="0x" + ("ab" * 32),
        chain_id="bitcoin:mainnet",
    )
    with pytest.raises(ValueError) as caught:
        CheckpointRecord(
            identity=CheckpointIdentity(
                chain=chain,
                provider="fixture",
                scope="wallet-review",
                normalized_schema_major=1,
                normalizer_version="review-v1",
            ),
            anchor=HashAnchor(sequence=1, block_hash="0xblock"),
            revision="rev:1",
            continuation_token=CANARY,
            metadata={"authorization": CANARY},
        )
    assert CANARY not in f"{caught.value!s}\n{caught.value!r}"

    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError) as caught_manifest:
        ExportManifest(
            chain=chain,
            provenance=Provenance(
                provider="fixture",
                provider_kind="offline",
                request_id="review",
                scope="bounded",
                observed_at=now,
            ),
            status=ExportStatus.COMPLETE,
            raw_payload_policy=RawPayloadPolicy.OMITTED,
            partitions=(),
            record_count=0,
            warning_count=1,
            finality_counts={Finality.FINALIZED: 0},
            started_at=now,
            completed_at=now,
            warnings=(CANARY,),
        )
    assert CANARY not in str(caught_manifest.value)

    safe_manifest = ExportManifest(
        chain=chain,
        provenance=Provenance(
            provider="fixture",
            provider_kind="offline",
            request_id="review",
            scope="bounded",
            observed_at=now,
        ),
        status=ExportStatus.COMPLETE,
        raw_payload_policy=RawPayloadPolicy.OMITTED,
        partitions=(),
        record_count=0,
        warning_count=0,
        finality_counts={},
        started_at=now,
        completed_at=now,
    )
    with pytest.raises(ExportError, match="wallet serialization") as caught_receipt:
        ExportReceipt(
            manifest=safe_manifest,
            status=ExportStatus.COMPLETE,
            output_dir="review-output",
            formats=("jsonl",),
            processor_version="review-v1",
            normalized_schema_major=1,
            warnings=(CANARY,),
        )
    assert CANARY not in str(caught_receipt.value)


def test_stored_raw_payload_dict_omits_body_bytes() -> None:
    stored = StoredRawPayload(
        digest="sha256:" + ("a" * 64),
        body=CANARY.encode(),
    )
    rendered = _render(stored, stored.to_dict())
    assert CANARY not in rendered
    assert CANARY.encode().hex() not in json.dumps(stored.to_dict(), default=str)
    assert stored.to_dict()["byte_length"] == len(CANARY.encode())


def test_world_id_redactor_strips_nested_private_evidence() -> None:
    raw = {
        "proof_id": "proof-safe",
        "proof": CANARY,
        "signature": CANARY,
        "public_inputs": {
            "binding_id": "binding-safe",
            "nullifier": CANARY,
            "provider_context": {
                "jwt": CANARY,
                "nested": {"private_key": CANARY, "network": "staging"},
            },
        },
        "safe": "visible",
    }
    safe = redact_world_id_payload(raw)
    rendered = json.dumps(safe, sort_keys=True)
    assert CANARY not in rendered
    assert "visible" in rendered
    assert safe["proof"] == "[redacted]"
    assert safe["public_inputs"]["provider_context"]["nested"]["network"] == "staging"


def test_world_id_result_never_serializes_raw_nullifier_or_portal_response() -> None:
    result = WorldIdVerificationResult(
        success=True,
        action="review",
        nullifier=CANARY,
        session_id=CANARY,
        results=({"success": True, "nullifier": CANARY, "proof": CANARY},),
        raw_response={"nullifier": CANARY, "proof": CANARY},
    )
    rendered = _render(result, result.public_dict(), result.to_dict())
    assert CANARY not in rendered
    assert result.public_dict()["has_nullifier"] is True
    assert result.public_dict()["has_session_id"] is True


def test_free_form_memos_and_instructions_default_to_bounded_redaction() -> None:
    memo_policy = MemoPrivacyPolicy(max_memo_data_bytes=8, max_memos=1)
    memos = memo_policy.apply_memos(
        [
            {"Memo": {"MemoData": CANARY}},
            {"Memo": {"MemoData": "second-memo-must-not-be-retained"}},
        ]
    )
    assert len(memos) == 1
    assert memos[0].memo_data is None
    assert memos[0].data_redacted is True
    assert memos[0].data_truncated is True
    assert CANARY not in _render(memos[0], memos[0].to_dict())

    instruction_policy = PayloadPrivacyPolicy(max_instruction_bytes=8)
    instruction = instruction_policy.apply_instruction(CANARY)
    request = instruction_policy.summarize_request(
        {"Memo": CANARY, "Calldata": CANARY, "TransactionType": "Payment"}
    )
    assert instruction["custom_instruction"] is None
    assert instruction["custom_instruction_redacted"] is True
    assert instruction["custom_instruction_truncated"] is True
    assert request == {"_redacted": True, "key_count": 3}
    assert CANARY not in _render(instruction, request)


def test_xaman_public_export_omits_tokens_secrets_and_instruction_body() -> None:
    processor = XamanWalletProcessor()
    payload = processor.normalize_payloads(
        [
            {
                "meta": {
                    "uuid": "00000000-0000-4000-8000-000000000001",
                    "signed": True,
                    "user_token": CANARY,
                },
                "payload": {
                    "custom_instruction": CANARY,
                    "txjson": {
                        "TransactionType": "Payment",
                        "DestinationTag": 7,
                        "Seed": CANARY,
                        "PrivateKey": CANARY,
                    },
                },
            }
        ],
        context=_context(),
    )[0]
    exported = processor.export_payloads_redacted([payload], context=_context())[0]
    serialized = json.dumps(exported, sort_keys=True)
    assert CANARY not in serialized
    assert "user_token" not in exported
    assert exported["custom_instruction"] is None
    assert exported["custom_instruction_redacted"] is True
    summary = json.dumps(exported.get("request_summary") or {})
    assert "Seed" not in summary
    assert "PrivateKey" not in summary


def test_xaman_request_summary_redacts_secret_shaped_fields_by_default() -> None:
    projection = PayloadPrivacyPolicy(
        redact_instruction=True,
        redact_request_body=False,
    ).summarize_request(
        {
            "TransactionType": "Payment",
            "PrivateKey": CANARY,
            "Authorization": CANARY,
            "Memos": [{"Memo": {"MemoData": CANARY}}],
        }
    )
    rendered = json.dumps(projection, sort_keys=True)
    assert CANARY not in rendered
    assert projection["TransactionType"] == "Payment"
    assert projection["Memos"]["present"] is True
    assert "PrivateKey" not in projection
    assert "Authorization" not in projection


def test_processor_surfaces_deny_sign_submit_and_broadcast_capabilities() -> None:
    denied = {
        "approve",
        "broadcast",
        "broadcast_transaction",
        "sign",
        "sign_payload",
        "sign_transaction",
        "submit",
        "submit_payload",
        "submit_transaction",
    }
    assert denied.isdisjoint({capability.value for capability in Capability})

    processor_types = (
        BitcoinWalletProcessor,
        XRPLWalletProcessor,
        XamanWalletProcessor,
        WorldChainProcessor,
        WorldIdProcessor,
    )
    for processor_type in processor_types:
        public_callables = {
            name
            for name, value in inspect.getmembers(processor_type, callable)
            if not name.startswith("_")
        }
        assert denied.isdisjoint(public_callables), processor_type.__name__

    xaman = XamanWalletProcessor()
    xaman.assert_read_only_surface()
    metadata = xaman.capabilities.metadata
    assert metadata.get("supports_sign") is False
    assert metadata.get("supports_submit") is False
    assert metadata.get("supports_broadcast") is False
    assert metadata.get("supports_approve") is False


def test_processor_tree_has_no_public_identity_clustering_or_custody_verbs() -> None:
    """Static guard for capability creep across chain modules not imported above."""

    forbidden_public_verbs = {
        "approve",
        "broadcast",
        "broadcast_transaction",
        "build_identity_graph",
        "cluster_addresses",
        "derive_private_key",
        "identify_owner",
        "infer_identity",
        "link_addresses",
        "sign",
        "sign_payload",
        "sign_transaction",
        "submit",
        "submit_payload",
        "submit_transaction",
    }
    package_root = Path(wallet_models.__file__).resolve().parent
    violations: list[str] = []
    for source_path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in forbidden_public_verbs:
                    violations.append(f"{source_path.relative_to(package_root)}:{node.name}")

    assert violations == []
    assert BitcoinWalletProcessor().capabilities.metadata["ownership_clustering"] is False


def test_exception_formatting_never_embeds_canary_or_endpoint() -> None:
    wrapped = InvalidRequestError(
        safe_exception_text("delegate failed", endpoint=ENDPOINT)
    )
    rendered = "".join(
        traceback.format_exception(type(wrapped), wrapped, wrapped.__traceback__)
    )
    assert CANARY not in str(wrapped)
    assert ENDPOINT not in str(wrapped)
    assert ENDPOINT not in rendered
    assert endpoint_fingerprint(ENDPOINT) in str(wrapped)
