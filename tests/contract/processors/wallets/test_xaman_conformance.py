"""Xaman wallet processor conformance suite (WALPROC-G210 / WALPROC-021).

Proves payload lifecycle distinctness, API≠settlement, XRPL settlement
verification, identity binding, redaction/size policy, and read-only surface.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.errors import NormalizationError
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.xaman import (
    ALL_PAYLOAD_STATUSES,
    PayloadPrivacyPolicy,
    PayloadStatus,
    SettlementVerdict,
    XamanPayloadProvider,
    XamanWalletProcessor,
    fixture_backend_from_payloads,
    parse_xaman_payload,
    verify_settlement_against_xrpl,
)
from ipfs_datasets_py.processors.wallets.xrpl.networks import XRPLNetwork

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "wallets" / "xaman"


def _load(name: str) -> dict:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _context(request_id: str = "xaman-conformance") -> OperationContext:
    return OperationContext(
        request_id=request_id,
        limits=RequestLimits(max_items=500, max_pages=20, max_requests=50),
    )


def test_fixture_manifest_acceptance_keys() -> None:
    manifest = _load("manifest.json")
    assert manifest["goal_id"] == "WALPROC-G210"
    assert manifest["classification"]["offline_default"] is True
    assert manifest["provenance"]["xaman_payloads"] is True
    assert manifest["provenance"]["api_success_is_settlement"] is False
    assert manifest["target_runtime_packages"]["status"] == "implemented"
    for relative in manifest["files"]:
        assert (_FIXTURE_DIR / relative).is_file(), relative
    required = {
        "distinct_payload_lifecycle_states",
        "api_success_is_not_settlement",
        "xrpl_settlement_verification",
        "network_account_payload_identity_bound",
        "memo_instruction_redaction_size_policy",
        "no_approve_sign_submit",
    }
    assert required <= set(manifest["acceptance_keys"])


def test_ast_symbols_importable() -> None:
    from ipfs_datasets_py.processors.wallets.xaman import (
        PayloadStatus,
        XamanPayload,
        XamanWalletProcessor,
    )

    assert XamanWalletProcessor is not None
    assert XamanPayload is not None
    assert PayloadStatus is not None
    assert len(ALL_PAYLOAD_STATUSES) == 10


def test_lifecycle_states_remain_distinct() -> None:
    data = _load("payload_lifecycle_states.json")
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)
    observed: dict[str, PayloadStatus] = {}
    for case in data["payloads"]:
        payload = processor.normalize_payloads(
            [case["document"]], context=_context(case["id"])
        )[0]
        observed[case["expect_status"]] = payload.status
        assert payload.status.value == case["expect_status"]
    assert set(observed) == set(data["required_statuses"])
    # Distinct enum members — no collapse.
    assert len(set(observed.values())) == len(observed)


def test_api_success_never_settlement_and_xrpl_verifies() -> None:
    life = _load("payload_lifecycle_states.json")
    by_id = {c["id"]: c for c in life["payloads"]}
    settle = _load("settlement_correlation.json")
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)

    for case in settle["cases"]:
        payload = processor.normalize_payloads(
            [by_id[case["payload_id"]]["document"]],
            context=_context(case["id"]),
        )[0]
        verified = processor.verify_settlement(
            payload,
            context=_context(f"settle-{case['id']}"),
            xrpl_transactions=case["xrpl_transactions"],
        )
        assert verified.settlement.value == case["expect_settlement"], case["id"]
        assert verified.is_ledger_settled is case["expect_ledger_settled"], case["id"]

    # Explicit rule: signed with txid but no ledger evidence.
    signed = parse_xaman_payload(
        by_id["signed"]["document"], network=XRPLNetwork.TESTNET
    )
    only_api = verify_settlement_against_xrpl(signed, xrpl_transactions=())
    assert only_api.is_api_success is True
    assert only_api.settlement is SettlementVerdict.API_SUCCESS_ONLY
    assert only_api.is_ledger_settled is False


def test_network_account_payload_identity_bound() -> None:
    data = _load("network_binding.json")
    for case in data["cases"]:
        network = XRPLNetwork(case["processor_network"])
        processor = XamanWalletProcessor(network=network)
        if "bind" in case:
            shell = processor.bind_identity(**case["bind"])
            assert shell.payload_uuid == case["expect"]["payload_uuid"]
            assert shell.account == case["expect"]["account"]
            assert shell.network.value == case["expect"]["network"]
            continue
        if case.get("expect_error"):
            with pytest.raises(NormalizationError):
                processor.normalize_payloads(
                    [case["document"]], context=_context(case["id"])
                )
            continue
        payload = processor.normalize_payloads(
            [case["document"]], context=_context(case["id"])
        )[0]
        assert payload.network.value == case["expect"]["network"]
        assert payload.account == case["expect"]["account"]
        assert payload.payload_uuid == case["expect"]["payload_uuid"]


def test_memos_and_payload_content_follow_redaction_size_policy() -> None:
    data = _load("redaction_cases.json")
    for case in data["cases"]:
        privacy_cfg = case.get("privacy") or {}
        privacy = PayloadPrivacyPolicy(
            redact_instruction=bool(privacy_cfg.get("redact_instruction", False)),
            max_instruction_bytes=int(privacy_cfg.get("max_instruction_bytes", 1024)),
        )
        processor = XamanWalletProcessor(
            network=XRPLNetwork.TESTNET, privacy=privacy
        )
        payload = processor.normalize_payloads(
            [case["document"]], context=_context(case["id"])
        )[0]
        expect = case.get("expect") or {}
        if expect.get("custom_instruction_redacted"):
            assert payload.custom_instruction is None
            assert payload.custom_instruction_redacted is True
        if expect.get("custom_instruction_truncated"):
            assert payload.custom_instruction_truncated is True
        if expect.get("secret_keys_absent_from_summary"):
            blob = json.dumps(payload.to_dict()).lower()
            assert "sedv" not in blob
            assert "sEdV" not in json.dumps(payload.to_dict())
        if "expect_export" in case:
            exported = processor.export_payloads_redacted(
                [payload], context=_context(f"export-{case['id']}")
            )[0]
            assert exported["custom_instruction"] is None
            assert exported["export_policy"]["api_success_is_settlement"] is False


def test_processor_cannot_approve_sign_or_submit() -> None:
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)
    processor.assert_read_only_surface()
    meta = processor.capabilities.metadata
    assert meta["supports_sign"] is False
    assert meta["supports_submit"] is False
    assert meta["supports_approve"] is False
    assert meta["supports_broadcast"] is False
    assert meta["api_success_is_settlement"] is False
    assert meta["xaman_payloads"] is True
    assert meta["settlement_via"] == "xrpl"
    for banned in (
        "approve",
        "approve_payload",
        "sign",
        "sign_payload",
        "submit",
        "submit_payload",
        "broadcast",
    ):
        assert not hasattr(processor, banned) or not callable(
            getattr(processor, banned, None)
        )


def test_offline_payload_ingest_composes_provider() -> None:
    data = _load("payload_lifecycle_states.json")
    docs = [c["document"] for c in data["payloads"]]
    backend = fixture_backend_from_payloads(docs)
    provider = XamanPayloadProvider(network=XRPLNetwork.TESTNET, backend=backend)
    processor = XamanWalletProcessor(
        network=XRPLNetwork.TESTNET, payload_provider=provider
    )

    async def _collect():
        out = []
        async for batch in processor.ingest_payloads(
            BoundedRequest(scope="payloads", context=_context("ingest"))
        ):
            out.extend(batch.records)
        return out

    records = asyncio.run(_collect())
    assert len(records) == len(docs)
    statuses = {r.status.value for r in records}
    assert "created" in statuses
    assert "signed" in statuses


def test_xaman_and_xrpl_remain_separate_modules() -> None:
    import ipfs_datasets_py.processors.wallets.xaman as xaman
    import ipfs_datasets_py.processors.wallets.xrpl as xrpl

    assert "XamanWalletProcessor" in xaman.__all__
    assert "XRPLWalletProcessor" in xrpl.__all__
    assert "XamanWalletProcessor" not in xrpl.__all__
    # Composition: Xaman holds an XRPL processor instance, not the reverse.
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)
    assert processor.xrpl is not None
    assert processor.xrpl.network is XRPLNetwork.TESTNET
