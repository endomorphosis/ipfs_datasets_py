"""Conformance tests for the isolated crypto-exchange Security adapter."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.security_ir.exchange.adapter import (
    EXCHANGE_ADAPTER_VERSION,
    ExchangeAdapterError,
    ExchangeSecurityAdapter,
    adapt_exchange_security_ir,
    to_legacy_exchange_security_ir,
    validate_exchange_security_ir,
)
from ipfs_datasets_py.logic.security_ir.exchange.vocabulary import (
    DEFAULT_EXCHANGE_CLAIMS_BY_ID,
    EXCHANGE_ASSUMPTIONS,
    EXCHANGE_EXTENSION_ID,
    EXCHANGE_VOCABULARY,
    EXCHANGE_VOCABULARY_SCHEMA_VERSION,
    EXCHANGE_VOCABULARY_VERSION,
    ExchangeVocabularyError,
    exchange_term,
    parse_exchange_term,
    validate_exchange_extension,
)
from ipfs_datasets_py.logic.security_ir.model import SecurityExtension
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
)


FIXTURES = (
    Path(__file__).resolve().parents[4] / "fixtures" / "security_ir" / "v1"
)


def _payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "exchange_model.json").read_text(encoding="utf-8")
    )


def _claim_digest(result: Any, claim_id: str) -> str:
    claim = next(
        item for item in result.declaration.claims if item.claim_id == claim_id
    )
    return str(claim.attributes["semantic_input_sha256"])


def test_vocabulary_is_namespaced_versioned_and_self_consistent() -> None:
    result = adapt_exchange_security_ir(_payload())
    extension = result.declaration.extensions[0]

    assert extension.extension_id == EXCHANGE_EXTENSION_ID
    assert extension.vocabulary == EXCHANGE_VOCABULARY
    assert extension.version == EXCHANGE_VOCABULARY_VERSION
    assert extension.required is True
    assert (
        extension.payload["schema_version"]
        == EXCHANGE_VOCABULARY_SCHEMA_VERSION
    )
    assert validate_exchange_extension(extension) is extension
    assert validate_exchange_security_ir(result.declaration) is result.declaration

    domain = exchange_term("domain", "withdrawals")
    assert parse_exchange_term(domain, category="domain") == "withdrawals"
    assert result.declaration.claims[0].domain == domain
    assert result.declaration.policies[0].name == exchange_term(
        "policy", "authorization_required"
    )
    wallet = next(
        item
        for item in result.declaration.resources
        if item.resource_id == "wallet:customer"
    )
    assert wallet.kind == exchange_term("resource", "wallet")
    assert result.declaration.assumptions[0].statement == EXCHANGE_ASSUMPTIONS["A3"]
    assert (
        DEFAULT_EXCHANGE_CLAIMS_BY_ID["no_unauthorized_withdrawal"].domain
        == "withdrawals"
    )


def test_vocabulary_validation_rejects_version_and_shape_drift() -> None:
    extension = adapt_exchange_security_ir(_payload()).declaration.extensions[0]
    wrong_version = replace(extension, version="v2")
    with pytest.raises(
        ExchangeVocabularyError, match="unsupported exchange vocabulary version"
    ):
        validate_exchange_extension(wrong_version)

    malformed = SecurityExtension(
        extension_id=EXCHANGE_EXTENSION_ID,
        vocabulary=EXCHANGE_VOCABULARY,
        version=EXCHANGE_VOCABULARY_VERSION,
        required=True,
        payload={
            **extension.to_dict()["payload"],
            "events": [
                {
                    "id": "event:unknown",
                    "event": "vendor_magic",
                    "custom": True,
                }
            ],
        },
    )
    with pytest.raises(ExchangeVocabularyError, match="unknown exchange event"):
        validate_exchange_extension(malformed)


def test_golden_exchange_model_round_trips_exactly() -> None:
    payload = _payload()
    result = adapt_exchange_security_ir(payload)

    assert result.adapter_version == EXCHANGE_ADAPTER_VERSION
    assert to_legacy_exchange_security_ir(result) == payload
    model = to_legacy_exchange_security_ir(result, as_model=True)
    assert isinstance(model, SecurityModelIR)
    assert model.to_dict() == payload

    facade = ExchangeSecurityAdapter()
    assert facade.to_legacy(facade.adapt(payload)) == payload


def test_exchange_adapter_defensively_copies_all_extension_values() -> None:
    payload = _payload()
    result = adapt_exchange_security_ir(payload)
    declaration = result.declaration.to_dict()

    payload["events"][0]["event"] = "withdrawal_cancelled"
    payload["capabilities"][0]["delegated_actions"].append("admin")
    payload["metadata"]["labels"].append("mutated")

    assert result.declaration.to_dict() == declaration
    with pytest.raises(TypeError):
        result.declaration.extensions[0].payload["events"][0]["event"] = "changed"


def test_semantic_mutations_change_only_claims_with_matching_inputs() -> None:
    before = _payload()
    withdrawal_mutation = copy.deepcopy(before)
    withdrawal_mutation["events"][1]["timestamp"] = 3
    metadata_mutation = copy.deepcopy(before)
    metadata_mutation["metadata"]["labels"].append("operational-only")

    baseline = adapt_exchange_security_ir(before)
    changed = adapt_exchange_security_ir(withdrawal_mutation)
    metadata_changed = adapt_exchange_security_ir(metadata_mutation)

    claim_id = "claim:golden-authorized-withdrawal"
    assert _claim_digest(baseline, claim_id) != _claim_digest(changed, claim_id)
    assert baseline.declaration.cid != changed.declaration.cid
    # Metadata is retained and therefore changes declaration identity, but it
    # is not an input to a withdrawal claim.
    assert (
        _claim_digest(baseline, claim_id)
        == _claim_digest(metadata_changed, claim_id)
    )
    assert baseline.declaration.cid != metadata_changed.declaration.cid


def test_validation_rejects_stale_claim_binding_after_semantic_mutation() -> None:
    result = adapt_exchange_security_ir(_payload())
    extension = result.declaration.extensions[0]
    payload = extension.to_dict()["payload"]
    payload["events"][1]["timestamp"] = 3
    mutated_extension = replace(extension, payload=payload)
    stale = replace(result.declaration, extensions=(mutated_extension,))

    with pytest.raises(ExchangeAdapterError, match="not bound to its current"):
        validate_exchange_security_ir(stale)


def test_unknown_extensions_fail_closed_without_declared_adapter() -> None:
    payload = _payload()
    payload["vendor_runtime_hint"] = {"mode": "offline"}

    with pytest.raises(
        ExchangeAdapterError, match="has no declared adapter"
    ):
        adapt_exchange_security_ir(payload)


def test_declared_extension_adapter_allows_validation_and_round_trip() -> None:
    payload = _payload()
    payload["vendor_runtime_hint"] = {"mode": "offline"}
    seen: list[str] = []

    def validate_vendor(extension: SecurityExtension) -> None:
        seen.append(extension.extension_id)
        assert extension.vocabulary == "legacy.security-model-ir"
        assert extension.payload["field_name"] == (
            "unsupported_vendor_runtime_hint"
        )

    adapter = ExchangeSecurityAdapter(
        extension_adapters={"vendor_runtime_hint": validate_vendor}
    )
    result = adapter.adapt(payload)

    assert seen
    assert adapter.validate(result.declaration) is result.declaration
    assert adapter.to_legacy(result) == payload


def test_exchange_adapter_rejects_non_exchange_golden_model() -> None:
    xaman = json.loads(
        (FIXTURES / "xaman_model.json").read_text(encoding="utf-8")
    )

    with pytest.raises(ExchangeAdapterError, match="outside the exchange vocabulary"):
        adapt_exchange_security_ir(xaman)
