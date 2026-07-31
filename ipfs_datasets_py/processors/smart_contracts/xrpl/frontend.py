"""XRPL native-ledger frontend (CRYPTOIR-G240).

Normalizes XRPL account flags, trust lines, escrows, checks, payment channels,
offers, AMMs, NFTs, signer lists, amendment/capability state, issuer freeze/
clawback, partial payment, reserve, sequence/ticket, destination tags, and
validated-ledger epochs into explicit native state-machine records.

Hooks return ``UNSUPPORTED`` where capability evidence is absent.
Ripple EVM sidechain requests **delegate** to the EVM frontend and are never
silently treated as XRPL mainnet.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..models import ensure_secret_safe
from .provider import OfflineXRPLProvider, XRPLLedgerFixture
from .semantics import (
    RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
    RIPPLE_EVM_SIDECHAIN_NAMESPACE,
    RIPPLE_EVM_SIDECHAIN_NETWORK,
    XRPL_MAINNET_CHAIN_ID,
    AmountKind,
    HookCapability,
    HookCapabilityState,
    IssuedAsset,
    IssuerPolicy,
    LedgerObjectKind,
    LedgerObjectTransition,
    SemanticPassStatus,
    SidechainRouting,
    SignerQuorum,
    ValidatedLedgerEpoch,
    XRPLTransactionType,
    default_object_kind_for_tx,
    incomplete_coverage_never_passes,
    is_ripple_evm_sidechain,
    map_transaction_type,
    normalize_classic_address,
    normalize_ledger_hash,
    partial_payment_flag_set,
    resolve_xrpl_chain_id,
    xrpl_network_anchor,
)


FRONTEND_SCHEMA_VERSION = "smart-contract-xrpl-frontend-v1"
FRONTEND_ID = "smart-contracts.xrpl.frontend"
FRONTEND_VERSION = "1.0.0"

DEFAULT_MAX_TRANSITIONS = 4_096
DEFAULT_MAX_OBJECTS = 16_384


class AnalysisMode(StrEnum):
    """How the frontend treated the observation."""

    NATIVE_LEDGER = "native_ledger"
    HOOKS_GATED = "hooks_gated"
    EVM_SIDECHAIN_DELEGATED = "evm_sidechain_delegated"
    UNSUPPORTED = "unsupported"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _optional_text(value: str | None, name: str) -> str:
    if value is None or value == "":
        return ""
    return _required_text(value, name)


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


@dataclass(frozen=True, slots=True)
class XRPLNormalizationResult:
    """Full frontend output for one XRPL (or sidechain-routed) observation."""

    analysis_mode: AnalysisMode
    routing: SidechainRouting
    chain_id: str
    network: str
    transitions: tuple[LedgerObjectTransition, ...] = ()
    ledger_epoch: ValidatedLedgerEpoch | None = None
    issuer_policy: IssuerPolicy | None = None
    hooks_capability: HookCapability | None = None
    signer_quorum: SignerQuorum | None = None
    semantic_pass_status: SemanticPassStatus = SemanticPassStatus.INCOMPLETE
    diagnostics: tuple[str, ...] = ()
    # When routing is EVM_SIDECHAIN, hold the delegated EVM frontend result dict.
    evm_delegation: Mapping[str, Any] | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        mode = (
            self.analysis_mode
            if isinstance(self.analysis_mode, AnalysisMode)
            else AnalysisMode(str(self.analysis_mode))
        )
        object.__setattr__(self, "analysis_mode", mode)
        routing = (
            self.routing
            if isinstance(self.routing, SidechainRouting)
            else SidechainRouting(str(self.routing))
        )
        object.__setattr__(self, "routing", routing)

        if routing is SidechainRouting.EVM_SIDECHAIN:
            # Sidechain must never claim XRPL mainnet identity.
            cid = _required_text(str(self.chain_id), "chain_id")
            if cid == XRPL_MAINNET_CHAIN_ID or cid in {"0", "mainnet", "xrpl-mainnet"}:
                raise InvalidRequestError(
                    "EVM sidechain result must not use XRPL mainnet chain_id"
                )
            object.__setattr__(self, "chain_id", cid)
            object.__setattr__(
                self,
                "network",
                self.network.strip() or RIPPLE_EVM_SIDECHAIN_NETWORK,
            )
        elif routing is SidechainRouting.XRPL_NATIVE:
            resolved = resolve_xrpl_chain_id(self.chain_id)
            anchor = xrpl_network_anchor(resolved)
            object.__setattr__(self, "chain_id", resolved)
            object.__setattr__(
                self, "network", self.network.strip() or anchor["network"]
            )
        else:
            object.__setattr__(
                self, "chain_id", _required_text(str(self.chain_id), "chain_id")
            )
            object.__setattr__(
                self, "network", _optional_text(self.network, "network")
            )

        transitions = tuple(self.transitions)
        for index, item in enumerate(transitions):
            if not isinstance(item, LedgerObjectTransition):
                raise InvalidRequestError(
                    f"transitions[{index}] must be a LedgerObjectTransition"
                )
        object.__setattr__(self, "transitions", transitions)

        if self.ledger_epoch is not None and not isinstance(
            self.ledger_epoch, ValidatedLedgerEpoch
        ):
            raise InvalidRequestError(
                "ledger_epoch must be ValidatedLedgerEpoch or None"
            )
        if self.issuer_policy is not None and not isinstance(
            self.issuer_policy, IssuerPolicy
        ):
            raise InvalidRequestError("issuer_policy must be IssuerPolicy or None")
        if self.hooks_capability is not None and not isinstance(
            self.hooks_capability, HookCapability
        ):
            raise InvalidRequestError(
                "hooks_capability must be HookCapability or None"
            )
        if self.signer_quorum is not None and not isinstance(
            self.signer_quorum, SignerQuorum
        ):
            raise InvalidRequestError("signer_quorum must be SignerQuorum or None")

        status = (
            self.semantic_pass_status
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.semantic_pass_status))
        )
        status = incomplete_coverage_never_passes(status)
        # Invariant: incomplete coverage never passes.
        if status is SemanticPassStatus.PASS:
            if routing is SidechainRouting.XRPL_NATIVE and not transitions:
                raise InvalidRequestError(
                    "semantic pass forbidden without at least one transition"
                )
            if (
                routing is SidechainRouting.EVM_SIDECHAIN
                and self.evm_delegation is None
            ):
                raise InvalidRequestError(
                    "EVM sidechain pass requires a delegated EVM result"
                )
        object.__setattr__(self, "semantic_pass_status", status)

        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        if self.evm_delegation is not None:
            if not isinstance(self.evm_delegation, Mapping):
                raise InvalidRequestError("evm_delegation must be a mapping or None")
            object.__setattr__(
                self, "evm_delegation", _freeze_mapping(self.evm_delegation)
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.semantic_pass_status is SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.analysis_mode.value
            if isinstance(self.analysis_mode, AnalysisMode)
            else str(self.analysis_mode),
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "diagnostics": list(self.diagnostics),
            "evm_delegation": thaw_json(self.evm_delegation)
            if self.evm_delegation is not None
            else None,
            "hooks_capability": self.hooks_capability.to_dict()
            if self.hooks_capability is not None
            else None,
            "issuer_policy": self.issuer_policy.to_dict()
            if self.issuer_policy is not None
            else None,
            "ledger_epoch": self.ledger_epoch.to_dict()
            if self.ledger_epoch is not None
            else None,
            "network": self.network,
            "routing": self.routing.value
            if isinstance(self.routing, SidechainRouting)
            else str(self.routing),
            "schema_version": self.schema_version,
            "semantic_pass_status": self.semantic_pass_status.value
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else str(self.semantic_pass_status),
            "signer_quorum": self.signer_quorum.to_dict()
            if self.signer_quorum is not None
            else None,
            "transitions": [item.to_dict() for item in self.transitions],
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


class XRPLLedgerFrontend:
    """Acquire/normalize XRPL native ledger objects into Crypto IR records.

    Designed for offline fixtures by default.  An optional
    :class:`OfflineXRPLProvider` may be injected; the frontend itself never
    opens sockets.  EVM sidechain identity always delegates to
    :class:`~..evm.frontend.EVMContractFrontend` and is never treated as
    XRPL mainnet.
    """

    def __init__(
        self,
        *,
        provider: OfflineXRPLProvider | None = None,
        max_transitions: int = DEFAULT_MAX_TRANSITIONS,
        max_objects: int = DEFAULT_MAX_OBJECTS,
        evm_frontend: Any | None = None,
    ) -> None:
        if (
            isinstance(max_transitions, bool)
            or not isinstance(max_transitions, int)
            or max_transitions <= 0
        ):
            raise InvalidRequestError("max_transitions must be a positive integer")
        if (
            isinstance(max_objects, bool)
            or not isinstance(max_objects, int)
            or max_objects <= 0
        ):
            raise InvalidRequestError("max_objects must be a positive integer")
        self._provider = provider
        self._max_transitions = max_transitions
        self._max_objects = max_objects
        self._evm_frontend = evm_frontend

    @property
    def frontend_id(self) -> str:
        return FRONTEND_ID

    @property
    def version(self) -> str:
        return FRONTEND_VERSION

    @property
    def provider(self) -> OfflineXRPLProvider | None:
        return self._provider

    def classify_routing(
        self,
        *,
        chain_id: str | int = "",
        network: str = "",
        namespace: str = "",
    ) -> SidechainRouting:
        """Classify whether a request is XRPL native or EVM sidechain.

        Ripple EVM sidechain is **never** silently treated as XRPL mainnet.
        """

        if is_ripple_evm_sidechain(chain_id, network):
            return SidechainRouting.EVM_SIDECHAIN
        ns = namespace.strip().lower() if namespace else ""
        if ns in {"eip155", "evm"} and str(chain_id).strip() == RIPPLE_EVM_SIDECHAIN_CHAIN_ID:
            return SidechainRouting.EVM_SIDECHAIN
        if ns in {"eip155", "evm"} and not is_ripple_evm_sidechain(chain_id, network):
            # Explicit EVM namespace that is not the known sidechain id.
            if str(chain_id).strip() in {XRPL_MAINNET_CHAIN_ID, "0"}:
                return SidechainRouting.REJECTED_CROSS_NETWORK
        try:
            resolve_xrpl_chain_id(chain_id, network)
            return SidechainRouting.XRPL_NATIVE
        except InvalidRequestError:
            if ns in {"eip155", "evm"}:
                return SidechainRouting.EVM_SIDECHAIN
            return SidechainRouting.UNKNOWN

    def bind_ledger_epoch(
        self,
        *,
        chain_id: str,
        ledger_index: int,
        ledger_hash: str,
        parent_hash: str = "",
        close_time: int | None = None,
        base_reserve_drops: str = "",
        owner_reserve_drops: str = "",
        enabled_amendments: Sequence[str] = (),
        network: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> ValidatedLedgerEpoch:
        """Bind a validated ledger coordinate and reserve/amendment state."""

        if is_ripple_evm_sidechain(chain_id, network):
            raise InvalidRequestError(
                "validated XRPL ledger epoch cannot bind Ripple EVM sidechain; "
                "use EVM frontend block epochs"
            )
        return ValidatedLedgerEpoch(
            chain_id=chain_id,
            ledger_index=ledger_index,
            ledger_hash=ledger_hash,
            validated=True,
            parent_hash=parent_hash,
            close_time=close_time,
            network=network,
            base_reserve_drops=base_reserve_drops,
            owner_reserve_drops=owner_reserve_drops,
            enabled_amendments=tuple(enabled_amendments),
            attributes=dict(attributes or {}),
        )

    def bind_issuer_policy(
        self,
        issuer: str,
        *,
        flags: int = 0,
        set_flag: int | None = None,
        clear_flag: int | None = None,
        allow_trustline_clawback: bool | None = None,
        require_auth: bool | None = None,
        default_ripple: bool | None = None,
        global_freeze: bool | None = None,
        no_freeze: bool | None = None,
        deposit_auth: bool | None = None,
        enabled_amendments: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> IssuerPolicy:
        """Bind issuer freeze/clawback/auth policy from account flags."""

        policy = IssuerPolicy.from_account_flags(
            issuer,
            flags=flags,
            set_flag=set_flag,
            clear_flag=clear_flag,
            allow_trustline_clawback=allow_trustline_clawback,
            enabled_amendments=enabled_amendments,
            attributes=attributes,
        )
        # Explicit overrides win when provided.
        return IssuerPolicy(
            issuer=policy.issuer,
            require_auth=policy.require_auth
            if require_auth is None
            else bool(require_auth),
            default_ripple=policy.default_ripple
            if default_ripple is None
            else bool(default_ripple),
            global_freeze=policy.global_freeze
            if global_freeze is None
            else bool(global_freeze),
            no_freeze=policy.no_freeze if no_freeze is None else bool(no_freeze),
            allow_trustline_clawback=policy.allow_trustline_clawback
            if allow_trustline_clawback is None
            else bool(allow_trustline_clawback),
            deposit_auth=policy.deposit_auth
            if deposit_auth is None
            else bool(deposit_auth),
            account_flags=policy.account_flags,
            enabled_amendments=policy.enabled_amendments,
            attributes=dict(policy.attributes),
        )

    def bind_hook_capability(
        self,
        *,
        chain_id: str,
        present: bool = False,
        capability_evidence: str = "",
        network: str = "",
        ledger_index: int | None = None,
        amendment_name: str = "Hooks",
    ) -> HookCapability:
        """Bind Hooks capability; absence yields ABSENT → UNSUPPORTED claims."""

        if is_ripple_evm_sidechain(chain_id, network):
            raise InvalidRequestError(
                "Hooks capability is XRPL-native; EVM sidechain uses EVM contracts"
            )
        if present:
            return HookCapability.proven(
                chain_id,
                capability_evidence=capability_evidence,
                network=network,
                ledger_index=ledger_index,
                amendment_name=amendment_name,
            )
        return HookCapability.absent(
            chain_id,
            network=network,
            diagnostics=("Hooks amendment not proven present",),
        )

    def bind_signer_quorum(
        self,
        account: str,
        *,
        quorum: int,
        signers: Sequence[Mapping[str, Any]] = (),
        signer_list_id: int = 0,
        attributes: Mapping[str, Any] | None = None,
    ) -> SignerQuorum:
        return SignerQuorum(
            account=account,
            quorum=quorum,
            signers=tuple(signers),
            signer_list_id=signer_list_id,
            attributes=dict(attributes or {}),
        )

    def bind_transition(
        self,
        *,
        transition_id: str,
        transaction_type: str | XRPLTransactionType,
        account: str,
        destination: str = "",
        destination_tag: int | None = None,
        source_tag: int | None = None,
        amount_kind: str = "",
        amount_value: str = "",
        issued_asset: IssuedAsset | Mapping[str, Any] | None = None,
        delivered_amount_kind: str = "",
        delivered_amount_value: str = "",
        delivered_issued_asset: IssuedAsset | Mapping[str, Any] | None = None,
        fee_drops: str = "",
        flags: int = 0,
        partial_payment: bool | None = None,
        sequence: int | None = None,
        ticket_sequence: int | None = None,
        last_ledger_sequence: int | None = None,
        signer_quorum: SignerQuorum | None = None,
        ledger_index: int | None = None,
        ledger_hash: str = "",
        transaction_hash: str = "",
        validated: bool | None = None,
        engine_result: str = "",
        memos: Sequence[Mapping[str, Any]] = (),
        trust_line: Mapping[str, Any] | None = None,
        issuer_policy: IssuerPolicy | None = None,
        hooks_capability: HookCapability | None = None,
        hooks_effects: Sequence[Mapping[str, Any]] = (),
        object_kind: str | LedgerObjectKind | None = None,
        object_id: str = "",
        previous_fields: Mapping[str, Any] | None = None,
        final_fields: Mapping[str, Any] | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> LedgerObjectTransition:
        """Bind one native ledger object transition from typed facts."""

        tx = map_transaction_type(transaction_type)
        kind = (
            default_object_kind_for_tx(tx)
            if object_kind is None
            else object_kind
        )
        issued: IssuedAsset | None = None
        if isinstance(issued_asset, IssuedAsset):
            issued = issued_asset
        elif isinstance(issued_asset, Mapping):
            issued = IssuedAsset.from_dict(issued_asset)
        del_issued: IssuedAsset | None = None
        if isinstance(delivered_issued_asset, IssuedAsset):
            del_issued = delivered_issued_asset
        elif isinstance(delivered_issued_asset, Mapping):
            del_issued = IssuedAsset.from_dict(delivered_issued_asset)

        flags_i = _non_negative(flags, "flags")
        partial = (
            partial_payment_flag_set(flags_i)
            if partial_payment is None
            else bool(partial_payment)
        )
        if partial_payment_flag_set(flags_i):
            partial = True

        # SetHook without proven hooks: still constructable, status UNSUPPORTED.
        # hooks_effects are rejected by LedgerObjectTransition without capability.
        return LedgerObjectTransition(
            transition_id=transition_id,
            transaction_type=tx,
            account=account,
            object_kind=kind,  # type: ignore[arg-type]
            destination=destination,
            destination_tag=destination_tag,
            source_tag=source_tag,
            amount_kind=amount_kind,
            amount_value=amount_value,
            issued_asset=issued,
            delivered_amount_kind=delivered_amount_kind,
            delivered_amount_value=delivered_amount_value,
            delivered_issued_asset=del_issued,
            fee_drops=fee_drops,
            flags=flags_i,
            partial_payment=partial,
            sequence=sequence,
            ticket_sequence=ticket_sequence,
            last_ledger_sequence=last_ledger_sequence,
            signer_quorum=signer_quorum,
            ledger_index=ledger_index,
            ledger_hash=ledger_hash,
            transaction_hash=transaction_hash,
            validated=validated,
            engine_result=engine_result,
            memos=tuple(memos),
            trust_line=trust_line,
            issuer_policy=issuer_policy,
            hooks_capability=hooks_capability,
            hooks_effects=tuple(hooks_effects),
            object_id=object_id,
            previous_fields=dict(previous_fields or {}),
            final_fields=dict(final_fields or {}),
            attributes=dict(attributes or {}),
        )

    def evaluate_hooks_claim(
        self,
        hooks_capability: HookCapability | None,
        *,
        transaction_type: str | XRPLTransactionType | None = None,
    ) -> SemanticPassStatus:
        """Return UNSUPPORTED when Hooks are absent; never invent Hook logic."""

        if hooks_capability is None:
            return SemanticPassStatus.UNSUPPORTED
        status = hooks_capability.evaluate_hook_claim()
        if transaction_type is not None:
            tx = map_transaction_type(transaction_type)
            if tx is XRPLTransactionType.SET_HOOK and status is not SemanticPassStatus.PASS:
                return SemanticPassStatus.UNSUPPORTED
        return status

    def normalize_from_fixture(
        self,
        fixture: XRPLLedgerFixture,
        *,
        transitions: Sequence[LedgerObjectTransition | Mapping[str, Any]] = (),
    ) -> XRPLNormalizationResult:
        """Normalize an offline ledger fixture into a full frontend result."""

        if not isinstance(fixture, XRPLLedgerFixture):
            raise InvalidRequestError("fixture must be a XRPLLedgerFixture")

        epoch = fixture.validated_epoch()
        policy = fixture.issuer_policy()
        hooks = fixture.hook_capability()
        signer: SignerQuorum | None = None
        if fixture.signer_list is not None:
            raw = dict(fixture.signer_list)
            signer = SignerQuorum(
                account=fixture.account,
                quorum=int(raw.get("quorum", raw.get("SignerQuorum", 1))),
                signers=tuple(raw.get("signers", raw.get("SignerEntries", ())) or ()),
                signer_list_id=int(raw.get("signer_list_id", raw.get("SignerListID", 0)) or 0),
            )

        bound: list[LedgerObjectTransition] = []
        for index, item in enumerate(transitions):
            if len(bound) >= self._max_transitions:
                raise ResourceLimitError("transitions exceed max_transitions")
            if isinstance(item, LedgerObjectTransition):
                bound.append(item)
            elif isinstance(item, Mapping):
                bound.append(LedgerObjectTransition.from_dict(item))
            else:
                raise InvalidRequestError(
                    f"transitions[{index}] must be LedgerObjectTransition or mapping"
                )

        object_count = (
            len(fixture.trust_lines)
            + len(fixture.escrows)
            + len(fixture.offers)
            + len(fixture.payment_channels)
            + len(fixture.checks)
            + len(fixture.amms)
            + len(fixture.nfts)
            + (1 if fixture.signer_list else 0)
        )
        if object_count > self._max_objects:
            raise ResourceLimitError("ledger objects exceed max_objects")

        diagnostics: list[str] = []
        statuses = [t.semantic_status() for t in bound]
        if not bound:
            # Fixture-only observation without explicit transitions is incomplete
            # unless we synthesize an account-root snapshot transition.
            diagnostics.append("no transitions bound; fixture snapshot only")
            statuses.append(SemanticPassStatus.INCOMPLETE)

        if hooks.state is not HookCapabilityState.PROVEN:
            diagnostics.append(
                "Hooks not proven; Hook claims return UNSUPPORTED"
            )

        # Aggregate status: worst-case fail-closed among transitions.
        status = SemanticPassStatus.PASS
        priority = {
            SemanticPassStatus.FAIL_CLOSED: 0,
            SemanticPassStatus.UNSUPPORTED: 1,
            SemanticPassStatus.UNKNOWN: 2,
            SemanticPassStatus.INCOMPLETE: 3,
            SemanticPassStatus.PASS: 4,
        }
        for s in statuses:
            if priority[s] < priority[status]:
                status = s

        mode = AnalysisMode.NATIVE_LEDGER
        if any(
            t.transaction_type is XRPLTransactionType.SET_HOOK
            or t.hooks_effects
            for t in bound
        ):
            mode = AnalysisMode.HOOKS_GATED
            if hooks.state is not HookCapabilityState.PROVEN:
                status = SemanticPassStatus.UNSUPPORTED
                mode = AnalysisMode.UNSUPPORTED

        return XRPLNormalizationResult(
            analysis_mode=mode,
            routing=SidechainRouting.XRPL_NATIVE,
            chain_id=fixture.chain_id,
            network=xrpl_network_anchor(fixture.chain_id)["network"],
            transitions=tuple(bound),
            ledger_epoch=epoch,
            issuer_policy=policy,
            hooks_capability=hooks,
            signer_quorum=signer,
            semantic_pass_status=status,
            diagnostics=tuple(diagnostics),
            attributes={
                "account": fixture.account,
                "fixture_key": fixture.fixture_key,
                "object_counts": {
                    "amms": len(fixture.amms),
                    "checks": len(fixture.checks),
                    "escrows": len(fixture.escrows),
                    "nfts": len(fixture.nfts),
                    "offers": len(fixture.offers),
                    "payment_channels": len(fixture.payment_channels),
                    "trust_lines": len(fixture.trust_lines),
                },
            },
        )

    def normalize_payment(
        self,
        *,
        chain_id: str,
        account: str,
        destination: str,
        amount_drops: str = "",
        issued_asset: IssuedAsset | Mapping[str, Any] | None = None,
        amount_value: str = "",
        delivered_amount_drops: str = "",
        delivered_amount_value: str = "",
        flags: int = 0,
        sequence: int | None = None,
        ticket_sequence: int | None = None,
        destination_tag: int | None = None,
        source_tag: int | None = None,
        fee_drops: str = "12",
        ledger_index: int | None = None,
        ledger_hash: str = "",
        transaction_hash: str = "",
        validated: bool = True,
        engine_result: str = "tesSUCCESS",
        transition_id: str = "",
        memos: Sequence[Mapping[str, Any]] = (),
    ) -> XRPLNormalizationResult:
        """Normalize a Payment transition (XRP or issued), including partial pay."""

        if is_ripple_evm_sidechain(chain_id):
            raise InvalidRequestError(
                "Payment normalization is XRPL-native; EVM sidechain uses EVM frontend"
            )
        resolved = resolve_xrpl_chain_id(chain_id)
        anchor = xrpl_network_anchor(resolved)

        issued: IssuedAsset | None = None
        if isinstance(issued_asset, IssuedAsset):
            issued = issued_asset
        elif isinstance(issued_asset, Mapping):
            issued = IssuedAsset.from_dict(issued_asset)

        if issued is not None:
            amount_kind = AmountKind.ISSUED.value
            amt = amount_value or "0"
            del_kind = AmountKind.ISSUED.value if delivered_amount_value else ""
            del_val = delivered_amount_value
            del_issued = issued if delivered_amount_value else None
        else:
            amount_kind = AmountKind.XRP.value
            amt = amount_drops or "0"
            del_kind = AmountKind.XRP.value if delivered_amount_drops else ""
            del_val = delivered_amount_drops
            del_issued = None

        tid = transition_id or (
            f"pay:{account}:{sequence if sequence is not None else ticket_sequence}"
        )
        transition = self.bind_transition(
            transition_id=tid,
            transaction_type=XRPLTransactionType.PAYMENT,
            account=account,
            destination=destination,
            destination_tag=destination_tag,
            source_tag=source_tag,
            amount_kind=amount_kind,
            amount_value=amt,
            issued_asset=issued,
            delivered_amount_kind=del_kind,
            delivered_amount_value=del_val,
            delivered_issued_asset=del_issued,
            fee_drops=fee_drops,
            flags=flags,
            sequence=sequence,
            ticket_sequence=ticket_sequence,
            ledger_index=ledger_index,
            ledger_hash=ledger_hash,
            transaction_hash=transaction_hash,
            validated=validated,
            engine_result=engine_result,
            memos=memos,
        )
        epoch = None
        if ledger_index is not None and ledger_hash:
            epoch = self.bind_ledger_epoch(
                chain_id=resolved,
                ledger_index=ledger_index,
                ledger_hash=ledger_hash,
            )
        status = transition.semantic_status()
        return XRPLNormalizationResult(
            analysis_mode=AnalysisMode.NATIVE_LEDGER,
            routing=SidechainRouting.XRPL_NATIVE,
            chain_id=resolved,
            network=anchor["network"],
            transitions=(transition,),
            ledger_epoch=epoch,
            semantic_pass_status=status,
            diagnostics=(),
            attributes={
                "partial_payment": transition.partial_payment,
                "destination_tag": destination_tag,
            },
        )

    def delegate_evm_sidechain(
        self,
        *,
        chain_id: str | int = RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
        address: str,
        runtime_bytecode: bytes | str = b"",
        creation_bytecode: bytes | str = b"",
        block_number: int | None = None,
        code_epoch: str = "",
        network: str = RIPPLE_EVM_SIDECHAIN_NETWORK,
        attributes: Mapping[str, Any] | None = None,
    ) -> XRPLNormalizationResult:
        """Delegate Ripple EVM sidechain analysis to the EVM frontend.

        Never treats the sidechain as XRPL mainnet.  Requires explicit
        sidechain identity; XRPL mainnet chain ids are rejected.
        """

        if not is_ripple_evm_sidechain(chain_id, network):
            # Also reject if someone passes XRPL mainnet.
            try:
                resolved_xrpl = resolve_xrpl_chain_id(chain_id, network)
            except InvalidRequestError:
                resolved_xrpl = ""
            if resolved_xrpl == XRPL_MAINNET_CHAIN_ID or str(chain_id).strip() in {
                "0",
                "mainnet",
                "xrpl-mainnet",
            }:
                raise InvalidRequestError(
                    "cannot delegate XRPL mainnet to EVM sidechain path; "
                    "networks are not interchangeable"
                )
            raise InvalidRequestError(
                f"chain_id {chain_id!r} is not the Ripple EVM sidechain "
                f"({RIPPLE_EVM_SIDECHAIN_CHAIN_ID})"
            )

        sidechain_id = str(chain_id).strip() or RIPPLE_EVM_SIDECHAIN_CHAIN_ID
        if sidechain_id == XRPL_MAINNET_CHAIN_ID:
            raise InvalidRequestError(
                "EVM sidechain chain_id must not equal XRPL mainnet"
            )

        diagnostics: list[str] = [
            "Ripple EVM sidechain delegated to EVM frontend",
            "not treated as XRPL mainnet native ledger",
        ]
        evm_payload: dict[str, Any] | None = None
        status = SemanticPassStatus.INCOMPLETE

        frontend = self._evm_frontend
        if frontend is None:
            try:
                from ..evm.frontend import EVMContractFrontend

                frontend = EVMContractFrontend()
            except Exception as exc:  # pragma: no cover - import failure path
                diagnostics.append(f"EVM frontend unavailable: {exc}")
                return XRPLNormalizationResult(
                    analysis_mode=AnalysisMode.EVM_SIDECHAIN_DELEGATED,
                    routing=SidechainRouting.EVM_SIDECHAIN,
                    chain_id=sidechain_id,
                    network=network or RIPPLE_EVM_SIDECHAIN_NETWORK,
                    semantic_pass_status=SemanticPassStatus.UNSUPPORTED,
                    diagnostics=tuple(diagnostics),
                    attributes={
                        "namespace": RIPPLE_EVM_SIDECHAIN_NAMESPACE,
                        "sidechain": True,
                        "xrpl_mainnet": False,
                        **dict(attributes or {}),
                    },
                )

        # Prefer full normalize_contract when bytecode present; else bind_code_epoch.
        runtime = runtime_bytecode if isinstance(runtime_bytecode, (bytes, str)) else b""
        creation = (
            creation_bytecode if isinstance(creation_bytecode, (bytes, str)) else b""
        )
        try:
            if hasattr(frontend, "normalize_contract") and (runtime or creation):
                result = frontend.normalize_contract(
                    chain_id=sidechain_id,
                    address=address,
                    runtime_bytecode=runtime,
                    creation_bytecode=creation,
                    block_number=block_number,
                    code_epoch=code_epoch,
                    network=network or RIPPLE_EVM_SIDECHAIN_NETWORK,
                )
                evm_payload = (
                    result.to_dict() if hasattr(result, "to_dict") else dict(result)
                )
                raw_status = getattr(result, "semantic_pass_status", None)
                if raw_status is not None:
                    status = SemanticPassStatus(
                        str(
                            raw_status.value
                            if hasattr(raw_status, "value")
                            else raw_status
                        )
                    )
                else:
                    status = (
                        SemanticPassStatus.PASS
                        if evm_payload
                        else SemanticPassStatus.INCOMPLETE
                    )
            elif hasattr(frontend, "bind_code_epoch") and runtime:
                epoch = frontend.bind_code_epoch(
                    chain_id=sidechain_id,
                    address=address,
                    runtime_bytecode=runtime,
                    block_number=block_number,
                    code_epoch=code_epoch,
                    network=network or RIPPLE_EVM_SIDECHAIN_NETWORK,
                )
                evm_payload = {
                    "code_epoch": epoch.to_dict()
                    if hasattr(epoch, "to_dict")
                    else {"address": address, "chain_id": sidechain_id},
                    "delegated": True,
                }
                status = SemanticPassStatus.PASS
            elif hasattr(frontend, "bind_code_epoch"):
                # No bytecode: record explicit incomplete delegation (not XRPL mainnet).
                diagnostics.append(
                    "EVM sidechain delegation without runtime bytecode is incomplete"
                )
                evm_payload = {
                    "address": address,
                    "block_number": block_number,
                    "chain_id": sidechain_id,
                    "code_epoch": code_epoch,
                    "delegated": True,
                    "namespace": RIPPLE_EVM_SIDECHAIN_NAMESPACE,
                }
                status = SemanticPassStatus.INCOMPLETE
            else:
                diagnostics.append("EVM frontend lacks normalize_contract/bind_code_epoch")
                status = SemanticPassStatus.UNSUPPORTED
                evm_payload = {
                    "address": address,
                    "chain_id": sidechain_id,
                    "delegated": True,
                    "namespace": RIPPLE_EVM_SIDECHAIN_NAMESPACE,
                }
        except Exception as exc:
            diagnostics.append(f"EVM delegation failed: {exc}")
            status = SemanticPassStatus.FAIL_CLOSED
            evm_payload = {
                "address": address,
                "chain_id": sidechain_id,
                "delegated": True,
                "error": str(exc),
            }

        return XRPLNormalizationResult(
            analysis_mode=AnalysisMode.EVM_SIDECHAIN_DELEGATED,
            routing=SidechainRouting.EVM_SIDECHAIN,
            chain_id=sidechain_id,
            network=network or RIPPLE_EVM_SIDECHAIN_NETWORK,
            semantic_pass_status=status,
            diagnostics=tuple(diagnostics),
            evm_delegation=evm_payload,
            attributes={
                "namespace": RIPPLE_EVM_SIDECHAIN_NAMESPACE,
                "sidechain": True,
                "xrpl_mainnet": False,
                "address": address,
                **dict(attributes or {}),
            },
        )

    def normalize(
        self,
        *,
        chain_id: str,
        network: str = "",
        namespace: str = "",
        # Native ledger path
        fixture: XRPLLedgerFixture | None = None,
        transitions: Sequence[LedgerObjectTransition | Mapping[str, Any]] = (),
        account: str = "",
        # Sidechain path
        address: str = "",
        runtime_bytecode: bytes | str = b"",
        creation_bytecode: bytes | str = b"",
        block_number: int | None = None,
        code_epoch: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> XRPLNormalizationResult:
        """Route and normalize an XRPL-native or EVM-sidechain observation."""

        routing = self.classify_routing(
            chain_id=chain_id, network=network, namespace=namespace
        )
        if routing is SidechainRouting.EVM_SIDECHAIN:
            if not address:
                raise InvalidRequestError(
                    "EVM sidechain normalization requires address"
                )
            return self.delegate_evm_sidechain(
                chain_id=chain_id,
                address=address,
                runtime_bytecode=runtime_bytecode,
                creation_bytecode=creation_bytecode,
                block_number=block_number,
                code_epoch=code_epoch,
                network=network or RIPPLE_EVM_SIDECHAIN_NETWORK,
                attributes=attributes,
            )
        if routing is SidechainRouting.REJECTED_CROSS_NETWORK:
            return XRPLNormalizationResult(
                analysis_mode=AnalysisMode.UNSUPPORTED,
                routing=routing,
                chain_id=str(chain_id),
                network=network or "",
                semantic_pass_status=SemanticPassStatus.FAIL_CLOSED,
                diagnostics=(
                    "cross-network identity rejected: eip155 namespace must not "
                    "claim XRPL mainnet chain_id",
                ),
                attributes=dict(attributes or {}),
            )
        if routing is SidechainRouting.UNKNOWN:
            return XRPLNormalizationResult(
                analysis_mode=AnalysisMode.UNSUPPORTED,
                routing=routing,
                chain_id=str(chain_id) if chain_id else "unknown",
                network=network or "",
                semantic_pass_status=SemanticPassStatus.UNKNOWN,
                diagnostics=("unable to classify chain as XRPL native or EVM sidechain",),
                attributes=dict(attributes or {}),
            )

        # XRPL native path
        if fixture is not None:
            return self.normalize_from_fixture(fixture, transitions=transitions)

        if not transitions and not account:
            raise InvalidRequestError(
                "native XRPL normalize requires fixture, transitions, or account"
            )

        resolved = resolve_xrpl_chain_id(chain_id, network)
        anchor = xrpl_network_anchor(resolved)
        bound: list[LedgerObjectTransition] = []
        for index, item in enumerate(transitions):
            if len(bound) >= self._max_transitions:
                raise ResourceLimitError("transitions exceed max_transitions")
            if isinstance(item, LedgerObjectTransition):
                bound.append(item)
            elif isinstance(item, Mapping):
                bound.append(LedgerObjectTransition.from_dict(item))
            else:
                raise InvalidRequestError(
                    f"transitions[{index}] must be LedgerObjectTransition or mapping"
                )

        diagnostics: list[str] = []
        if not bound:
            diagnostics.append("no transitions supplied")
            status = SemanticPassStatus.INCOMPLETE
        else:
            status = SemanticPassStatus.PASS
            priority = {
                SemanticPassStatus.FAIL_CLOSED: 0,
                SemanticPassStatus.UNSUPPORTED: 1,
                SemanticPassStatus.UNKNOWN: 2,
                SemanticPassStatus.INCOMPLETE: 3,
                SemanticPassStatus.PASS: 4,
            }
            for t in bound:
                s = t.semantic_status()
                if priority[s] < priority[status]:
                    status = s

        return XRPLNormalizationResult(
            analysis_mode=AnalysisMode.NATIVE_LEDGER,
            routing=SidechainRouting.XRPL_NATIVE,
            chain_id=resolved,
            network=network or anchor["network"],
            transitions=tuple(bound),
            semantic_pass_status=status,
            diagnostics=tuple(diagnostics),
            attributes={
                "account": account,
                **dict(attributes or {}),
            },
        )


__all__ = [
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "DEFAULT_MAX_TRANSITIONS",
    "DEFAULT_MAX_OBJECTS",
    "AnalysisMode",
    "XRPLNormalizationResult",
    "XRPLLedgerFrontend",
]
