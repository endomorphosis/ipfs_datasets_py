"""Xaman wallet and payload processing over XRPL (WALPROC-G210).

Public module separate from :mod:`..xrpl`. Composes the XRPL ledger processor
for settlement verification. Payload lifecycle states remain distinct, and
Xaman API success is never treated as ledger settlement.

No approve / sign / submit surface is exposed. Formal assurance modules under
``logic/`` are intentionally not imported here (see WALPROC-G220).
"""

from __future__ import annotations

from .models import (
    ALL_PAYLOAD_STATUSES,
    AccountActivityCorrelation,
    NON_SETTLEMENT_API_STATUSES,
    PayloadStatus,
    SettlementVerdict,
    XamanPayload,
    parse_payload_status,
    resolve_payload_status_from_meta,
)
from .normalizer import (
    EXTENSION_NAMESPACE,
    EXTENSION_SCHEMA,
    PROVIDER_KIND,
    bind_network_account_payload,
    parse_xaman_payload,
)
from .privacy import (
    DEFAULT_MAX_INSTRUCTION_BYTES,
    DEFAULT_MAX_REQUEST_SUMMARY_KEYS,
    DEFAULT_MAX_STRING_FIELD_BYTES,
    PayloadPrivacyPolicy,
)
from .processor import PROCESSOR_NAME, XamanWalletProcessor
from .provider import (
    DEFAULT_API_BASE,
    PROVIDER_FAMILY,
    PROVIDER_NAME,
    HttpPayloadBackend,
    MappingPayloadBackend,
    XamanPayloadProvider,
    fixture_backend_from_payloads,
)
from .settlement import (
    SettlementEvidence,
    correlate_account_activity,
    evidence_from_xrpl_transaction,
    verify_settlement_against_xrpl,
)

__all__ = [
    "ALL_PAYLOAD_STATUSES",
    "AccountActivityCorrelation",
    "DEFAULT_API_BASE",
    "DEFAULT_MAX_INSTRUCTION_BYTES",
    "DEFAULT_MAX_REQUEST_SUMMARY_KEYS",
    "DEFAULT_MAX_STRING_FIELD_BYTES",
    "EXTENSION_NAMESPACE",
    "EXTENSION_SCHEMA",
    "HttpPayloadBackend",
    "MappingPayloadBackend",
    "NON_SETTLEMENT_API_STATUSES",
    "PROCESSOR_NAME",
    "PROVIDER_FAMILY",
    "PROVIDER_KIND",
    "PROVIDER_NAME",
    "PayloadPrivacyPolicy",
    "PayloadStatus",
    "SettlementEvidence",
    "SettlementVerdict",
    "XamanPayload",
    "XamanPayloadProvider",
    "XamanWalletProcessor",
    "bind_network_account_payload",
    "correlate_account_activity",
    "evidence_from_xrpl_transaction",
    "fixture_backend_from_payloads",
    "parse_payload_status",
    "parse_xaman_payload",
    "resolve_payload_status_from_meta",
    "verify_settlement_against_xrpl",
]
