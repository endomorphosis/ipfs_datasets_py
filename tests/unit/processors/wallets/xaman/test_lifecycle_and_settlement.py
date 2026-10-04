"""Lifecycle distinctness, API≠settlement, XRPL verification, identity binding."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.wallets.errors import NormalizationError
from ipfs_datasets_py.processors.wallets.protocols import OperationContext
from ipfs_datasets_py.processors.wallets.xaman import (
    ALL_PAYLOAD_STATUSES,
    PayloadPrivacyPolicy,
    PayloadStatus,
    SettlementVerdict,
    XamanWalletProcessor,
    parse_xaman_payload,
    verify_settlement_against_xrpl,
)
from ipfs_datasets_py.processors.wallets.xrpl.networks import XRPLNetwork


def test_all_payload_statuses_are_distinct() -> None:
    values = [s.value for s in PayloadStatus]
    assert len(values) == len(set(values))
    assert set(values) == {
        "created",
        "opened",
        "signed",
        "rejected",
        "expired",
        "cancelled",
        "submitted",
        "validated",
        "failed",
        "unknown",
    }
    assert ALL_PAYLOAD_STATUSES == frozenset(PayloadStatus)


def test_lifecycle_fixture_covers_every_status(load_xaman_fixture) -> None:
    data = load_xaman_fixture("payload_lifecycle_states.json")
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)
    seen: set[str] = set()
    for case in data["payloads"]:
        records = processor.normalize_payloads(
            [case["document"]],
            context=OperationContext(request_id=f"life-{case['id']}"),
        )
        assert len(records) == 1
        payload = records[0]
        assert payload.status.value == case["expect_status"]
        seen.add(payload.status.value)
    assert seen == set(data["required_statuses"])


def test_api_success_is_never_settlement_without_xrpl(load_xaman_fixture) -> None:
    life = load_xaman_fixture("payload_lifecycle_states.json")
    by_id = {c["id"]: c for c in life["payloads"]}
    settle = load_xaman_fixture("settlement_correlation.json")
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)

    for case in settle["cases"]:
        doc = by_id[case["payload_id"]]["document"]
        payload = processor.normalize_payloads(
            [doc], context=OperationContext(request_id=case["id"])
        )[0]
        verified = processor.verify_settlement(
            payload,
            context=OperationContext(request_id=f"v-{case['id']}"),
            xrpl_transactions=case["xrpl_transactions"],
        )
        assert verified.settlement.value == case["expect_settlement"]
        assert verified.is_ledger_settled is case["expect_ledger_settled"]
        if verified.is_api_success and not case["expect_ledger_settled"]:
            assert verified.settlement is not SettlementVerdict.XRPL_VALIDATED
            assert verified.settlement in {
                SettlementVerdict.API_SUCCESS_ONLY,
                SettlementVerdict.NETWORK_MISMATCH,
                SettlementVerdict.ACCOUNT_MISMATCH,
                SettlementVerdict.XRPL_FAILED,
                SettlementVerdict.XRPL_UNVALIDATED,
                SettlementVerdict.UNKNOWN,
            }


def test_signed_api_success_without_txid_is_api_success_only() -> None:
    raw = {
        "meta": {
            "uuid": "44444444-4444-4444-8444-444444444401",
            "signed": True,
            "resolved": True,
            "network": "testnet",
        },
        "payload": {
            "txjson": {
                "TransactionType": "Payment",
                "Account": "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
                "Destination": "r3bmF74WayREhyVYaqbu7GqLKvqZvUF3k6",
                "Amount": "1",
            }
        },
        "response": {},
    }
    payload = parse_xaman_payload(raw, network=XRPLNetwork.TESTNET)
    assert payload.status is PayloadStatus.SIGNED
    assert payload.is_api_success is True
    verified = verify_settlement_against_xrpl(payload, xrpl_transactions=())
    assert verified.settlement is SettlementVerdict.API_SUCCESS_ONLY
    assert verified.is_ledger_settled is False


def test_network_account_payload_identity_bound(load_xaman_fixture, op_context) -> None:
    data = load_xaman_fixture("network_binding.json")
    for case in data["cases"]:
        network = XRPLNetwork(case["processor_network"])
        processor = XamanWalletProcessor(network=network)
        if "bind" in case:
            shell = processor.bind_identity(**case["bind"])
            assert shell.network.value == case["expect"]["network"]
            assert shell.account == case["expect"]["account"]
            assert shell.payload_uuid == case["expect"]["payload_uuid"]
            assert shell.status.value == case["expect"]["status"]
            continue
        if case.get("expect_error") == "NormalizationError":
            with pytest.raises(NormalizationError):
                processor.normalize_payloads([case["document"]], context=op_context)
            continue
        payload = processor.normalize_payloads(
            [case["document"]], context=op_context
        )[0]
        assert payload.network.value == case["expect"]["network"]
        assert payload.account == case["expect"]["account"]
        assert payload.payload_uuid == case["expect"]["payload_uuid"]


def test_redaction_and_size_policy(load_xaman_fixture, op_context) -> None:
    data = load_xaman_fixture("redaction_cases.json")
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
            [case["document"]], context=op_context
        )[0]
        expect = case.get("expect") or {}
        if "custom_instruction" in expect:
            assert payload.custom_instruction == expect["custom_instruction"]
        if expect.get("custom_instruction_redacted"):
            assert payload.custom_instruction_redacted is True
        if expect.get("custom_instruction_truncated"):
            assert payload.custom_instruction_truncated is True
            assert (
                len(payload.custom_instruction.encode("utf-8"))
                <= expect["max_instruction_bytes"]
            )
        if expect.get("secret_keys_absent_from_summary"):
            summary_text = str(payload.request_summary).lower()
            assert "secret" not in summary_text
            assert "sedv" not in summary_text
            assert "signingpubkey" not in summary_text.replace("_", "")
        if "expect_export" in case:
            exported = processor.export_payloads_redacted(
                [payload], context=op_context, force_redact_instruction=True
            )[0]
            assert exported["custom_instruction"] is None
            assert exported["custom_instruction_redacted"] is True
            assert exported["export_policy"]["api_success_is_settlement"] is False


def test_account_activity_correlation(load_xaman_fixture, op_context) -> None:
    life = load_xaman_fixture("payload_lifecycle_states.json")
    submitted = next(c for c in life["payloads"] if c["id"] == "submitted")
    processor = XamanWalletProcessor(network=XRPLNetwork.TESTNET)
    payload = processor.normalize_payloads(
        [submitted["document"]], context=op_context
    )[0]
    corr = processor.correlate_activity(
        payload,
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        context=op_context,
        xrpl_transactions=[
            {
                "hash": payload.transaction_hash,
                "account": "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
                "validated": True,
                "outcome": "validated_success",
                "ledger_index": 42,
                "network": "xrpl-testnet",
            }
        ],
    )
    assert corr.settlement is SettlementVerdict.XRPL_VALIDATED
    assert payload.transaction_hash in corr.matching_ledger_hashes
