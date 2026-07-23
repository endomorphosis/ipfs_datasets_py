from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.mcp_server.mcplusplus.profile_h import (
    CatalogSigner,
    DatasetPaymentError,
    PaidDatasetService,
)
from mcplusplus_profile_h import Decision, PaymentContext, RequestContext
from mcplusplus_profile_h.canonical import cid_for


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "protected_datasets.json").read_text())


def params(fixture, *, version="3"):
    return {
        "datasetId": "medical-records", "version": version, "tenant": "clinic-a",
        **fixture["privateInput"], "fields": fixture["fields"], "rowFilter": fixture["rowFilter"],
        "limit": 20, "privacy": {"mode": "aggregate", "k": 5},
    }


def payment(required):
    return PaymentContext(
        {"x402Version": 2, "accepted": required.payment_required["accepts"][0],
         "payload": {"signature": "private-wallet-material"}},
        required.receipt_cid, required.quote["requestCid"],
    )


def test_signed_catalog_is_versioned_and_scope_committed(service):
    catalog = service.catalog()
    assert CatalogSigner.verify(catalog)
    assert catalog["pricingModel"] == "fixed-dataset-version"
    assert catalog["signedCatalogCid"].startswith("baguq")
    assert {item["metadata"]["operation"] for item in catalog["capabilities"]} == {
        "query/execute", "transform/run", "graphrag/query"
    }
    assert {item["metadata"]["datasetVersion"] for item in catalog["capabilities"]} == {
        "medical-records@3", "medical-records@4"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FIXTURES["operations"], ids=lambda item: item["name"])
async def test_query_transform_and_graphrag_are_payment_fenced(service, request_context, calls, fixture):
    starts = []

    async def effect(handoff):
        starts.append(handoff)
        assert "query" not in handoff and "transform" not in handoff and "question" not in handoff
        assert handoff["entitlementCid"].startswith("baguq")
        return {"protected": "result-content"}

    required = await service.dispatch(fixture["name"], request_context, params(fixture), effect)
    assert required.decision.decision == Decision.PAYMENT_REQUIRED
    assert starts == [] and calls == {"verify": 0, "settle": 0}
    accepted = await service.dispatch(fixture["name"], request_context, params(fixture), effect, payment=payment(required))
    assert accepted.decision.decision == Decision.PAID
    assert len(starts) == calls["verify"] == calls["settle"] == 1
    assert accepted.value["usageRecordCid"].startswith("baguq")
    assert accepted.value["provenanceCid"].startswith("baguq")
    assert accepted.value["outputReceiptCid"].startswith("baguq")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"context": {"licenses": ()}}, "H_LICENSE_REQUIRED"),
        ({"context": {"tenant": "clinic-b"}}, "H_TENANT_SCOPE_DENIED"),
        ({"params": {"rowFilter": {"region": "eu"}}}, "H_ROW_SCOPE_DENIED"),
        ({"params": {"fields": ["patient_name"]}}, "H_FIELD_SCOPE_DENIED"),
        ({"params": {"privacy": {"mode": "raw", "k": 5}}}, "H_PRIVACY_POLICY_DENIED"),
    ],
)
async def test_non_payment_controls_deny_before_quote_or_effect(service, request_context, calls, change, code):
    fixture = FIXTURES["operations"][0]
    attributes = dict(request_context.attributes)
    attributes.update(change.get("context", {}))
    context = RequestContext(request_context.request_cid, request_context.idempotency_key, attributes=attributes)
    arguments = {**params(fixture), **change.get("params", {})}
    with pytest.raises(DatasetPaymentError) as raised:
        await service.dispatch(fixture["name"], context, arguments, lambda: pytest.fail("data accessed"))
    assert raised.value.code == code
    assert calls == {"verify": 0, "settle": 0}


@pytest.mark.asyncio
async def test_entitlement_cannot_cross_query_or_version(service, request_context, calls):
    fixture = FIXTURES["operations"][0]
    original = params(fixture)
    required = await service.dispatch(fixture["name"], request_context, original, lambda: None)
    paid = await service.dispatch(fixture["name"], request_context, original, lambda _: {"rows": ["secret"]},
                                  payment=payment(required))
    replay = await service.dispatch(fixture["name"], request_context, original, lambda: pytest.fail("duplicate"))
    assert replay.replayed and replay.value["entitlementCid"] == paid.value["entitlementCid"]
    with pytest.raises(Exception) as query_replay:
        await service.dispatch(fixture["name"], request_context, {**original, "query": "different"}, lambda: None)
    assert getattr(query_replay.value, "code", None) == "H_REQUEST_MISMATCH"
    with pytest.raises(Exception) as version_replay:
        await service.dispatch(fixture["name"], request_context, {**original, "version": "4", "limit": 20}, lambda: None)
    assert getattr(version_replay.value, "code", None) == "H_REQUEST_MISMATCH"
    assert calls["settle"] == 1


@pytest.mark.asyncio
async def test_public_evidence_is_cid_linked_and_contains_no_content(service, request_context):
    fixture = FIXTURES["operations"][2]
    arguments = params(fixture)
    required = await service.dispatch(fixture["name"], request_context, arguments, lambda: None)
    paid = await service.dispatch(fixture["name"], request_context, arguments,
                                  lambda _: {"answer": "highly protected answer", "nodes": ["alice"]},
                                  payment=payment(required))
    evidence = [service.artifacts.get(paid.value[key]) for key in
                ("entitlementCid", "usageRecordCid", "provenanceCid", "outputReceiptCid")]
    serialized = json.dumps(evidence, sort_keys=True)
    assert "highly protected" not in serialized and "Which diagnoses" not in serialized and "alice" not in serialized
    assert evidence[2]["parents"] == [paid.value["entitlementCid"], paid.value["usageRecordCid"]]
    assert evidence[3]["parents"] == [paid.value["usageRecordCid"], paid.value["provenanceCid"]]


@pytest.mark.asyncio
async def test_http_and_libp2p_parity(service, request_context):
    fixture = FIXTURES["operations"][0]
    arguments = params(fixture)
    status, headers, _body = await service.handle_http(
        "POST", "/mcp/datasets/query", request_context, arguments, lambda: {"ok": True}
    )
    assert status == 402 and "PAYMENT-REQUIRED" in headers
    required = await service.dispatch(fixture["name"], request_context, arguments, lambda: None)
    pay = payment(required)
    encoded = base64.b64encode(json.dumps({"payload": pay.payload, "quoteCid": pay.quote_cid,
                                           "requestCid": pay.request_cid}).encode()).decode()
    status, headers, body = await service.handle_http(
        "POST", "/mcp/datasets/query", request_context, arguments,
        lambda _: {"ok": True}, payment_header=encoded,
    )
    assert status == 200 and "PAYMENT-RESPONSE" in headers and body["outcome"] == "succeeded"
    wire = await service.handle_libp2p({"operation": fixture["name"], "params": arguments},
                                      request_context, lambda: pytest.fail("duplicate query"))
    assert wire["receipt_cid"]
    control = await service.handle_profile_h_libp2p({
        "jsonrpc": "2.0", "id": 1, "method": "mcp++/payments/profile", "params": {},
    })
    assert control["result"]["ready"] is True
    http_status, _, http_profile = await service.profile_h_http_app.handle("GET", "/mcp/payments/profile")
    assert http_status == 200 and http_profile == control["result"]


@pytest.mark.asyncio
async def test_restart_preserves_catalog_and_receipts(tmp_path, config, facilitator, request_context, calls):
    state = tmp_path / "persistent"
    fixture = FIXTURES["operations"][1]
    first = PaidDatasetService(config, state, facilitator)
    required = await first.dispatch(fixture["name"], request_context, params(fixture), lambda: None)
    paid = await first.dispatch(fixture["name"], request_context, params(fixture), lambda _: {"ok": True},
                                payment=payment(required))
    restarted = PaidDatasetService(config, state, facilitator)
    assert restarted.catalog() == first.catalog()
    replay = await restarted.dispatch(fixture["name"], request_context, params(fixture),
                                      lambda: pytest.fail("duplicate transform"))
    assert replay.replayed and replay.value["outputReceiptCid"] == paid.value["outputReceiptCid"]
    diagnostics = await restarted.diagnostics()
    assert diagnostics["catalogSignatureValid"] is True and calls["settle"] == 1
