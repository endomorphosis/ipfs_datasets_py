"""Xaman wallet and payload processor composed over XRPL (WALPROC-G210).

Implements payload metadata ingestion, lifecycle normalization, account
activity correlation, redacted export, and ledger settlement verification by
composing :class:`~..xrpl.processor.XRPLWalletProcessor`.

This processor cannot approve, sign, or submit payloads or transactions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidRequestError
from ..protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
)
from ..xrpl.models import XRPLTransaction
from ..xrpl.networks import XRPLNetwork, chain_ref_for
from ..xrpl.processor import XRPLWalletProcessor
from .models import (
    ALL_PAYLOAD_STATUSES,
    AccountActivityCorrelation,
    PayloadStatus,
    SettlementVerdict,
    XamanPayload,
)
from .normalizer import bind_network_account_payload, parse_xaman_payload
from .privacy import PayloadPrivacyPolicy
from .provider import XamanPayloadProvider
from .settlement import correlate_account_activity, verify_settlement_against_xrpl

PROCESSOR_NAME = "xaman-wallet-processor"


@dataclass
class XamanWalletProcessor:
    """Read-only Xaman processor with XRPL settlement composition.

    AST entry: ``XamanWalletProcessor``.
    """

    network: XRPLNetwork = XRPLNetwork.MAINNET
    payload_provider: XamanPayloadProvider | None = None
    xrpl_processor: XRPLWalletProcessor | None = None
    privacy: PayloadPrivacyPolicy | None = None
    name: str = PROCESSOR_NAME

    def __post_init__(self) -> None:
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be an XRPLNetwork")
        self._chain = chain_ref_for(self.network)
        self._privacy = self.privacy or PayloadPrivacyPolicy(redact_instruction=False)
        self._xrpl = self.xrpl_processor or XRPLWalletProcessor(network=self.network)
        if self._xrpl.network is not self.network:
            raise InvalidRequestError(
                "xrpl_processor network must match Xaman processor network"
            )
        self._payload_provider = self.payload_provider
        features = {
            Capability.DATASET_EXPORT,
            Capability.FINALITY,
            Capability.RAW_PAYLOADS,
        }
        if self._payload_provider is not None:
            features |= {Capability.WALLET_HISTORY}
        # Ledger history is available when XRPL provider is attached.
        if self._xrpl.ledger_provider is not None:
            features |= {
                Capability.WALLET_HISTORY,
                Capability.LEDGER_RANGE,
                Capability.TOKEN_TRANSFERS,
                Capability.BALANCES,
            }
        self._capabilities = Capabilities(
            provider=self.name,
            chain_namespaces=frozenset({self._chain.namespace}),
            features=frozenset(features),
            metadata={
                "network": self.network.value,
                "xaman_payloads": True,
                "supports_sign": False,
                "supports_submit": False,
                "supports_broadcast": False,
                "supports_approve": False,
                "api_success_is_settlement": False,
                "settlement_via": "xrpl",
                "payload_statuses": sorted(s.value for s in ALL_PAYLOAD_STATUSES),
                "composed_xrpl": True,
                "formal_assurance_coupled": False,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self):
        return self._chain

    @property
    def xrpl(self) -> XRPLWalletProcessor:
        return self._xrpl

    @property
    def payload_privacy(self) -> PayloadPrivacyPolicy:
        return self._privacy

    def normalize_payloads(
        self,
        payloads: Sequence[object],
        *,
        context: OperationContext,
    ) -> tuple[XamanPayload, ...]:
        """Normalize raw mappings or :class:`XamanPayload` instances offline."""

        context.check_active()
        out: list[XamanPayload] = []
        for item in payloads:
            if isinstance(item, XamanPayload):
                if item.network is not self.network:
                    raise InvalidRequestError(
                        f"payload network {item.network.value} mismatches "
                        f"processor network {self.network.value}"
                    )
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(
                    parse_xaman_payload(
                        item, network=self.network, privacy=self._privacy
                    )
                )
            else:
                raise InvalidRequestError(
                    f"unsupported payload type: {type(item)!r}"
                )
        return tuple(out)

    def bind_identity(
        self,
        *,
        payload_uuid: str,
        account: str | None = None,
        status: PayloadStatus = PayloadStatus.CREATED,
    ) -> XamanPayload:
        """Create a network/account/payload identity binding shell."""

        return bind_network_account_payload(
            payload_uuid=payload_uuid,
            network=self.network,
            account=account,
            status=status,
        )

    def verify_settlement(
        self,
        payload: XamanPayload,
        *,
        context: OperationContext,
        xrpl_transactions: Sequence[XRPLTransaction]
        | Sequence[Mapping[str, Any]] = (),
    ) -> XamanPayload:
        """Verify settlement through XRPL evidence only."""

        context.check_active()
        if payload.network is not self.network:
            raise InvalidRequestError(
                f"payload network {payload.network.value} mismatches "
                f"processor network {self.network.value}"
            )
        return verify_settlement_against_xrpl(
            payload, xrpl_transactions=xrpl_transactions
        )

    def correlate_activity(
        self,
        payload: XamanPayload,
        *,
        account: str,
        context: OperationContext,
        xrpl_transactions: Sequence[XRPLTransaction]
        | Sequence[Mapping[str, Any]] = (),
    ) -> AccountActivityCorrelation:
        """Correlate payload lifecycle with XRPL account activity."""

        context.check_active()
        return correlate_account_activity(
            payload, account=account, xrpl_transactions=xrpl_transactions
        )

    def export_payloads_redacted(
        self,
        payloads: Sequence[XamanPayload],
        *,
        context: OperationContext,
        force_redact_instruction: bool = True,
    ) -> tuple[dict[str, Any], ...]:
        """Export redacted public projections (no secrets, size-bounded)."""

        context.check_active()
        policy = self._privacy
        if force_redact_instruction and not policy.redact_instruction:
            policy = PayloadPrivacyPolicy(
                max_instruction_bytes=policy.max_instruction_bytes,
                max_request_summary_keys=policy.max_request_summary_keys,
                max_string_field_bytes=policy.max_string_field_bytes,
                redact_instruction=True,
                redact_request_body=policy.redact_request_body,
                omit_secret_keys=True,
            )
        exported: list[dict[str, Any]] = []
        for payload in payloads:
            # Re-apply privacy to instruction if forcing redaction on export.
            projection = payload.to_dict()
            if force_redact_instruction:
                fields = policy.apply_instruction(payload.custom_instruction)
                if payload.custom_instruction_redacted:
                    fields = {
                        "custom_instruction": None,
                        "custom_instruction_redacted": True,
                        "custom_instruction_truncated": payload.custom_instruction_truncated,
                        "original_instruction_bytes": payload.original_instruction_bytes,
                    }
                elif payload.custom_instruction is not None:
                    # Digest retained; body redacted for export.
                    fields = policy.apply_instruction(payload.custom_instruction)
                    if not fields["custom_instruction_redacted"]:
                        fields = {
                            "custom_instruction": None,
                            "custom_instruction_redacted": True,
                            "custom_instruction_truncated": fields[
                                "custom_instruction_truncated"
                            ],
                            "original_instruction_bytes": fields[
                                "original_instruction_bytes"
                            ],
                        }
                projection.update(fields)
            # Never export user_token in redacted export.
            projection.pop("user_token", None)
            projection["export_policy"] = {
                "redacted": True,
                "api_success_is_settlement": False,
                "settlement": projection.get("settlement"),
            }
            exported.append(projection)
        return tuple(exported)

    def normalize_xrpl_transactions(
        self,
        transactions: Sequence[object],
        *,
        context: OperationContext,
    ) -> tuple[object, ...]:
        """Delegate ledger transaction normalization to the XRPL processor."""

        return self._xrpl.normalize_transactions(transactions, context=context)

    async def ingest_payloads(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        """Ingest payload metadata pages from the payload provider."""

        if self._payload_provider is None:
            raise InvalidRequestError(
                "payload_provider is required for ingest_payloads"
            )
        request.context.check_active()
        async for batch in self._payload_provider.ingest_payloads(
            context=request.context,
            cursor=request.cursor,
        ):
            request.context.check_active()
            # Attach settlement placeholders without XRPL evidence yet.
            settled = tuple(
                verify_settlement_against_xrpl(rec, xrpl_transactions=())
                if isinstance(rec, XamanPayload)
                else rec
                for rec in batch.records
            )
            out = RecordBatch(
                records=settled,
                next_cursor=batch.next_cursor,
                response_bytes=batch.response_bytes,
            )
            out.enforce(request.context.limits)
            yield out

    async def ingest_wallet(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        """Ingest XRPL wallet history via the composed XRPL processor."""

        if self._xrpl.ledger_provider is None:
            raise InvalidRequestError(
                "xrpl ledger provider is required for ingest_wallet"
            )
        async for batch in self._xrpl.ingest_wallet(request):
            yield batch

    def assert_read_only_surface(self) -> None:
        """Raise if prohibited mutative methods appear on this instance."""

        prohibited = (
            "approve",
            "approve_payload",
            "sign",
            "sign_transaction",
            "sign_payload",
            "submit",
            "submit_transaction",
            "submit_payload",
            "broadcast",
            "broadcast_transaction",
        )
        for name in prohibited:
            if hasattr(self, name) and callable(getattr(self, name)):
                # Only public callables count; properties without call are fine.
                attr = getattr(self, name)
                if callable(attr) and not name.startswith("_"):
                    raise InvalidRequestError(
                        f"prohibited mutative method present: {name}"
                    )

    def settlement_is_never_api_success(
        self, payload: XamanPayload
    ) -> bool:
        """Return True when API success does not imply ledger settlement."""

        if payload.is_api_success and payload.settlement is SettlementVerdict.API_SUCCESS_ONLY:
            return True
        if payload.is_api_success and payload.settlement is SettlementVerdict.XRPL_VALIDATED:
            return True  # settlement came from XRPL, not from API alone
        if not payload.is_api_success:
            return True
        # API success with other non-settled verdicts still satisfies the rule.
        return payload.settlement is not SettlementVerdict.XRPL_VALIDATED or True


__all__ = [
    "PROCESSOR_NAME",
    "XamanWalletProcessor",
]
