"""World Chain contract and World ID verifier frontend (CRYPTOIR-G260).

Composes EVM contract semantics for World Chain and adds explicit World ID
verifier, external-nullifier, action/domain, bridge, proxy-upgrade, and replay
boundary records.

Acceptance invariants:

* Verifier and implementation code epochs are pinned and comparable.
* Chain / domain / action / external-nullifier bindings are mandatory.
* Proof-consumer behavior is explicit: a valid identity proof never implies
  payment authorization, legal identity, or contract safety.
* Every external verifier and bridge trust assumption is stated.
* Proxy upgrades and replay boundaries fail closed.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..evm.frontend import (
    AnalysisMode,
    EVMCodeEpoch,
    EVMContractFrontend,
    EVMNormalizationResult,
    SourceEquivalenceStatus,
)
from ..evm.proxies import ProxyBinding, ProxyKind, RedeploymentRisk
from ..evm.semantics import SemanticPassStatus as EVMSemanticPassStatus
from ..models import ensure_secret_safe
from .semantics import (
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_SETTLEMENT,
    WORLD_ID_PROOF_TYPE,
    BridgeBinding,
    BridgeDirection,
    ExternalNullifier,
    ProofConsumerBehavior,
    ProofImplication,
    ReplayDomain,
    SemanticPassStatus,
    TrustAssumption,
    TrustSurface,
    VerifierKind,
    WorldIDVerifierBinding,
    check_nullifier_replay,
    check_verifier_upgrade,
    default_bridge_trust_assumptions,
    default_verifier_trust_assumptions,
    is_world_chain_id,
    normalize_address,
    require_stated_trust,
    world_chain_anchor,
)


FRONTEND_SCHEMA_VERSION = "smart-contract-worldcoin-frontend-v1"
FRONTEND_ID = "smart-contracts.worldcoin.frontend"
FRONTEND_VERSION = "1.0.0"


class CompositionMode(StrEnum):
    """How World Chain analysis relates to the composed EVM frontend."""

    EVM_COMPOSED = "evm_composed"
    WORLD_ID_ONLY = "world_id_only"
    BRIDGE_ONLY = "bridge_only"
    FULL_COMPOSITION = "full_composition"


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


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def _require_world_chain(chain_id: str | int, name: str = "chain_id") -> str:
    text = _required_text(str(chain_id), name)
    if not is_world_chain_id(text):
        raise InvalidRequestError(
            f"{name} must be World Chain 480 or 4801 (got {text!r})"
        )
    return text


@dataclass(frozen=True, slots=True)
class WorldcoinNormalizationResult:
    """Full World Chain + World ID frontend output for one composition."""

    composition_mode: CompositionMode
    chain_id: str
    network: str
    settlement_layer: str
    evm_result: EVMNormalizationResult | None = None
    verifier_binding: WorldIDVerifierBinding | None = None
    external_nullifier: ExternalNullifier | None = None
    replay_domain: ReplayDomain | None = None
    proof_consumer: ProofConsumerBehavior | None = None
    bridge: BridgeBinding | None = None
    verifier_trust: tuple[TrustAssumption, ...] = ()
    bridge_trust: tuple[TrustAssumption, ...] = ()
    pass_status: SemanticPassStatus = SemanticPassStatus.INCOMPLETE
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        mode = self.composition_mode
        if not isinstance(mode, CompositionMode):
            mode = CompositionMode(str(mode))
        object.__setattr__(self, "composition_mode", mode)
        chain = _require_world_chain(self.chain_id)
        anchor = world_chain_anchor(chain)
        object.__setattr__(self, "chain_id", chain)
        object.__setattr__(
            self, "network", self.network.strip() or anchor["network"]
        )
        object.__setattr__(
            self,
            "settlement_layer",
            self.settlement_layer.strip() or anchor["settlement_layer"],
        )
        if self.evm_result is not None and not isinstance(
            self.evm_result, EVMNormalizationResult
        ):
            raise InvalidRequestError("evm_result must be EVMNormalizationResult or None")
        if self.verifier_binding is not None and not isinstance(
            self.verifier_binding, WorldIDVerifierBinding
        ):
            raise InvalidRequestError(
                "verifier_binding must be WorldIDVerifierBinding or None"
            )
        if self.external_nullifier is not None and not isinstance(
            self.external_nullifier, ExternalNullifier
        ):
            raise InvalidRequestError(
                "external_nullifier must be ExternalNullifier or None"
            )
        if self.replay_domain is not None and not isinstance(
            self.replay_domain, ReplayDomain
        ):
            raise InvalidRequestError("replay_domain must be ReplayDomain or None")
        if self.proof_consumer is not None and not isinstance(
            self.proof_consumer, ProofConsumerBehavior
        ):
            raise InvalidRequestError(
                "proof_consumer must be ProofConsumerBehavior or None"
            )
        if self.bridge is not None and not isinstance(self.bridge, BridgeBinding):
            raise InvalidRequestError("bridge must be BridgeBinding or None")

        v_trust = tuple(self.verifier_trust)
        for index, item in enumerate(v_trust):
            if not isinstance(item, TrustAssumption):
                raise InvalidRequestError(
                    f"verifier_trust[{index}] must be a TrustAssumption"
                )
        object.__setattr__(self, "verifier_trust", v_trust)

        b_trust = tuple(self.bridge_trust)
        for index, item in enumerate(b_trust):
            if not isinstance(item, TrustAssumption):
                raise InvalidRequestError(
                    f"bridge_trust[{index}] must be a TrustAssumption"
                )
        object.__setattr__(self, "bridge_trust", b_trust)

        status = self.pass_status
        if not isinstance(status, SemanticPassStatus):
            status = SemanticPassStatus(str(status))
        object.__setattr__(self, "pass_status", status)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )

        # Hard invariants: proof never elevates to payment / legal / safety.
        if self.proof_consumer is not None:
            if self.proof_consumer.implies_payment:
                raise InvalidRequestError(
                    "proof_consumer must not imply payment authority"
                )
            if self.proof_consumer.implies_legal_identity:
                raise InvalidRequestError(
                    "proof_consumer must not imply legal identity"
                )
            if self.proof_consumer.implies_contract_safety:
                raise InvalidRequestError(
                    "proof_consumer must not imply contract safety"
                )
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.pass_status is SemanticPassStatus.PASS

    def stated_trust_assumptions(self) -> tuple[TrustAssumption, ...]:
        """All external verifier and bridge trust assumptions on this result."""

        return self.verifier_trust + self.bridge_trust

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "bridge": self.bridge.to_dict() if self.bridge is not None else None,
            "bridge_trust": [item.to_dict() for item in self.bridge_trust],
            "chain_id": self.chain_id,
            "composition_mode": self.composition_mode.value
            if isinstance(self.composition_mode, CompositionMode)
            else str(self.composition_mode),
            "diagnostics": list(self.diagnostics),
            "evm_result": self.evm_result.to_dict()
            if self.evm_result is not None
            else None,
            "external_nullifier": self.external_nullifier.to_dict()
            if self.external_nullifier is not None
            else None,
            "network": self.network,
            "pass_status": self.pass_status.value
            if isinstance(self.pass_status, SemanticPassStatus)
            else str(self.pass_status),
            "proof_consumer": self.proof_consumer.to_dict()
            if self.proof_consumer is not None
            else None,
            "proof_type": WORLD_ID_PROOF_TYPE,
            "replay_domain": self.replay_domain.to_dict()
            if self.replay_domain is not None
            else None,
            "schema_version": self.schema_version,
            "settlement_layer": self.settlement_layer,
            "stated_trust_assumptions": [
                item.to_dict() for item in self.stated_trust_assumptions()
            ],
            "verifier_binding": self.verifier_binding.to_dict()
            if self.verifier_binding is not None
            else None,
            "verifier_trust": [item.to_dict() for item in self.verifier_trust],
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


class WorldcoinContractFrontend:
    """Compose EVM frontend for World Chain with World ID verifier semantics.

    AST surface: WorldcoinContractFrontend, WorldIDVerifierBinding,
    ExternalNullifier, ReplayDomain.
    """

    def __init__(
        self,
        *,
        evm_frontend: EVMContractFrontend | None = None,
        max_bytecode_bytes: int = 24_576,
        max_instructions: int = 65_536,
    ) -> None:
        if (
            isinstance(max_bytecode_bytes, bool)
            or not isinstance(max_bytecode_bytes, int)
            or max_bytecode_bytes <= 0
        ):
            raise InvalidRequestError("max_bytecode_bytes must be a positive integer")
        if (
            isinstance(max_instructions, bool)
            or not isinstance(max_instructions, int)
            or max_instructions <= 0
        ):
            raise InvalidRequestError("max_instructions must be a positive integer")
        self._evm = evm_frontend or EVMContractFrontend(
            max_bytecode_bytes=max_bytecode_bytes,
            max_instructions=max_instructions,
        )
        self._max_bytecode_bytes = max_bytecode_bytes
        self._max_instructions = max_instructions
        # In-memory replay index for adversarial fixture evaluation (offline).
        self._replay_index: dict[str, ReplayDomain] = {}

    @property
    def frontend_id(self) -> str:
        return FRONTEND_ID

    @property
    def version(self) -> str:
        return FRONTEND_VERSION

    @property
    def evm_frontend(self) -> EVMContractFrontend:
        return self._evm

    # ------------------------------------------------------------------
    # Domain / nullifier / verifier binding
    # ------------------------------------------------------------------

    def bind_external_nullifier(
        self,
        *,
        rp_id: str,
        action: str,
        environment: str,
        app_id: str = "",
        protocol_version: str = "4.0",
        signal_hash_ref: str = "",
        chain_id: str = "",
        network: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> ExternalNullifier:
        """Bind RP/app/action/environment into an ExternalNullifier domain."""

        return ExternalNullifier(
            rp_id=rp_id,
            action=action,
            environment=environment,
            app_id=app_id,
            protocol_version=protocol_version,
            signal_hash_ref=signal_hash_ref,
            chain_id=chain_id,
            network=network,
            attributes=dict(attributes or {}),
        )

    def bind_replay_domain(
        self,
        *,
        external_nullifier: ExternalNullifier,
        nullifier_commitment: str,
        binding_id: str = "",
        used: bool = False,
        attributes: Mapping[str, Any] | None = None,
        register: bool = False,
    ) -> ReplayDomain:
        """Bind a privacy-safe nullifier commitment into a ReplayDomain."""

        domain = ReplayDomain(
            external_nullifier=external_nullifier,
            nullifier_commitment=nullifier_commitment,
            binding_id=binding_id,
            used=used,
            attributes=dict(attributes or {}),
        )
        if register:
            status = self.register_replay_domain(domain)
            if status is SemanticPassStatus.REPLAY_CONFLICT:
                raise InvalidRequestError(
                    "nullifier already used in this external-nullifier domain"
                )
            if status is SemanticPassStatus.DOMAIN_MISMATCH:
                raise InvalidRequestError(
                    "nullifier commitment collides across incompatible domains"
                )
        return domain

    def register_replay_domain(self, domain: ReplayDomain) -> SemanticPassStatus:
        """Register a replay domain; fail closed on same-domain reuse."""

        if not isinstance(domain, ReplayDomain):
            raise InvalidRequestError("domain must be a ReplayDomain")
        existing = self._replay_index.get(domain.nullifier_commitment)
        if existing is None:
            # Store as used once registered (first use consumes the nullifier).
            consumed = ReplayDomain(
                external_nullifier=domain.external_nullifier,
                nullifier_commitment=domain.nullifier_commitment,
                binding_id=domain.binding_id,
                used=True,
                attributes=dict(domain.attributes),
            )
            self._replay_index[domain.nullifier_commitment] = consumed
            return SemanticPassStatus.PASS
        return check_nullifier_replay(existing, domain)

    def clear_replay_index(self) -> None:
        """Clear the offline replay index (test / fixture isolation)."""

        self._replay_index.clear()

    def bind_verifier(
        self,
        *,
        verifier_id: str,
        verifier_address: str,
        code_epoch: str,
        external_nullifier: ExternalNullifier,
        chain_id: str | int,
        protocol_version: str = "4.0",
        verifier_kind: VerifierKind | str = VerifierKind.ON_CHAIN_WORLD_ID,
        implementation_address: str = "",
        implementation_code_digest: str = "",
        proxy_kind: str = "",
        network: str = "",
        genesis_hash: str = "",
        block_number: int | None = None,
        include_default_trust: bool = True,
        extra_trust: Sequence[TrustAssumption] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> WorldIDVerifierBinding:
        """Bind a World ID verifier with pinned code epoch and domain."""

        chain = _require_world_chain(chain_id)
        kind = (
            verifier_kind
            if isinstance(verifier_kind, VerifierKind)
            else VerifierKind(str(verifier_kind))
        )
        trust_ids: list[str] = []
        if include_default_trust:
            for item in default_verifier_trust_assumptions(
                verifier_kind=kind,
                code_epoch_pinned=bool(code_epoch),
            ):
                trust_ids.append(item.assumption_id)
        for item in extra_trust:
            if not isinstance(item, TrustAssumption):
                raise InvalidRequestError(
                    "extra_trust items must be TrustAssumption instances"
                )
            trust_ids.append(item.assumption_id)

        # Align external nullifier chain when unbound.
        nullifier = external_nullifier
        if not nullifier.chain_id:
            nullifier = ExternalNullifier(
                rp_id=external_nullifier.rp_id,
                action=external_nullifier.action,
                environment=external_nullifier.environment,
                app_id=external_nullifier.app_id,
                protocol_version=protocol_version,
                signal_hash_ref=external_nullifier.signal_hash_ref,
                chain_id=chain,
                network=network or world_chain_anchor(chain)["network"],
                attributes=dict(external_nullifier.attributes),
            )
        elif nullifier.protocol_version != protocol_version:
            # Re-bind with matching protocol if caller set domain protocol differently.
            raise InvalidRequestError(
                "external_nullifier protocol_version must match verifier protocol_version"
            )

        return WorldIDVerifierBinding(
            verifier_id=verifier_id,
            verifier_address=verifier_address,
            code_epoch=code_epoch,
            external_nullifier=nullifier,
            chain_id=chain,
            protocol_version=protocol_version,
            verifier_kind=kind,
            implementation_address=implementation_address,
            implementation_code_digest=implementation_code_digest,
            proxy_kind=proxy_kind,
            network=network,
            genesis_hash=genesis_hash,
            block_number=block_number,
            trusted_assumptions=tuple(dict.fromkeys(trust_ids)),
            attributes=dict(attributes or {}),
        )

    def bind_bridge(
        self,
        *,
        bridge_id: str,
        source_chain_id: str | int,
        destination_chain_id: str | int,
        direction: BridgeDirection | str = BridgeDirection.UNKNOWN,
        asset_symbol: str = "",
        amount_base_units: str = "",
        tx_hash_ref: str = "",
        code_epoch: str = "",
        settlement_layer: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> BridgeBinding:
        """Bind a bridge observation with every required trust assumption."""

        src = str(source_chain_id).strip()
        dst = str(destination_chain_id).strip()
        # Determine settlement from the World Chain side.
        if is_world_chain_id(src):
            settlement = settlement_layer or world_chain_anchor(src)["settlement_layer"]
        elif is_world_chain_id(dst):
            settlement = settlement_layer or world_chain_anchor(dst)["settlement_layer"]
        else:
            settlement = settlement_layer or WORLD_CHAIN_MAINNET_SETTLEMENT

        direction_enum = (
            direction
            if isinstance(direction, BridgeDirection)
            else BridgeDirection(str(direction))
        )
        return BridgeBinding(
            bridge_id=bridge_id,
            source_chain_id=src,
            destination_chain_id=dst,
            direction=direction_enum,
            asset_symbol=asset_symbol,
            amount_base_units=amount_base_units,
            tx_hash_ref=tx_hash_ref,
            code_epoch=code_epoch,
            trusted_assumptions=default_bridge_trust_assumptions(
                settlement_layer=settlement
            ),
            attributes=dict(attributes or {}),
        )

    # ------------------------------------------------------------------
    # Proof-consumer behavior
    # ------------------------------------------------------------------

    def evaluate_proof_consumer(
        self,
        *,
        verification_status: str,
        external_nullifier: ExternalNullifier,
        nullifier_commitment: str,
        verifier_binding: WorldIDVerifierBinding | None = None,
        claim_payment_authorization: bool = False,
        claim_legal_identity: bool = False,
        claim_contract_safety: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> ProofConsumerBehavior:
        """Evaluate proof-consumer behavior with fail-closed non-implications.

        Even when *verification_status* is verified, payment/legal/safety claims
        are rejected and recorded as diagnostics.
        """

        diagnostics: list[str] = []
        status = SemanticPassStatus.INCOMPLETE

        verified = verification_status.strip().lower() in {
            "verified",
            "success",
            "ok",
            "valid",
        }
        if not verified:
            status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append(
                f"verification_status={verification_status!r} is not verified"
            )
        else:
            status = SemanticPassStatus.PASS
            diagnostics.append("world_id_proof_verified")

        if claim_payment_authorization:
            status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append(
                "rejected: valid identity proof never implies payment authority"
            )
        if claim_legal_identity:
            status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append(
                "rejected: valid identity proof never implies legal identity"
            )
        if claim_contract_safety:
            status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append(
                "rejected: valid identity proof never implies contract safety"
            )

        if verifier_binding is not None:
            # Domain must match.
            if not (
                verifier_binding.external_nullifier.domain_key
                == external_nullifier.domain_key
                or (
                    verifier_binding.external_nullifier.rp_id == external_nullifier.rp_id
                    and verifier_binding.external_nullifier.action
                    == external_nullifier.action
                    and verifier_binding.external_nullifier.environment
                    == external_nullifier.environment
                )
            ):
                status = SemanticPassStatus.DOMAIN_MISMATCH
                diagnostics.append(
                    "proof domain does not match verifier external-nullifier binding"
                )
            trust_status = require_stated_trust(
                [
                    TrustAssumption(
                        surface=TrustSurface.WORLD_ID_VERIFIER,
                        assumption_id=aid,
                        statement=aid,
                    )
                    for aid in verifier_binding.trusted_assumptions
                ]
                if verifier_binding.trusted_assumptions
                else default_verifier_trust_assumptions(
                    verifier_kind=verifier_binding.verifier_kind
                ),
                required_surfaces=(TrustSurface.WORLD_ID_VERIFIER,),
            )
            # When assumptions are id-only stubs above, require_stated_trust may
            # see WORLD_ID_VERIFIER.  For empty trusted_assumptions, inject defaults
            # check differently.
            if not verifier_binding.trusted_assumptions:
                status = SemanticPassStatus.TRUST_UNSTATED
                diagnostics.append("verifier trust assumptions unstated")
            elif "worldcoin.proof_not_payment_authority" not in set(
                verifier_binding.trusted_assumptions
            ):
                diagnostics.append(
                    "missing worldcoin.proof_not_payment_authority assumption"
                )
                if status is SemanticPassStatus.PASS:
                    status = SemanticPassStatus.TRUST_UNSTATED
            _ = trust_status  # surface required; status already derived above

        return ProofConsumerBehavior(
            verification_status=verification_status,
            external_nullifier=external_nullifier,
            nullifier_commitment=nullifier_commitment,
            verifier_binding=verifier_binding,
            forbidden_implications=(
                ProofImplication.PAYMENT,
                ProofImplication.LEGAL_IDENTITY,
                ProofImplication.CONTRACT_SAFETY,
                ProofImplication.ACCOUNT_CONTROL,
                ProofImplication.ASSET_TRANSFER,
                ProofImplication.UPGRADE,
                ProofImplication.BRIDGE_FINALITY,
            ),
            pass_status=status,
            diagnostics=tuple(diagnostics),
            attributes=dict(attributes or {}),
        )

    # ------------------------------------------------------------------
    # EVM composition for World Chain contracts
    # ------------------------------------------------------------------

    def normalize_world_chain_contract(
        self,
        *,
        chain_id: str | int,
        address: str,
        runtime_bytecode: bytes | str,
        block_number: int | None = None,
        code_epoch: str = "",
        creation_bytecode: bytes | str = b"",
        compiler: str = "",
        compiler_version: str = "",
        compiler_flags: Mapping[str, Any] | None = None,
        libraries: Mapping[str, str] | None = None,
        constructor_args: bytes | str = b"",
        metadata_policy: str = "embedded-cbor-ipfs-none",
        abi: bytes | str = b"",
        storage: Mapping[str, str] | None = None,
        previous_code_digest: str = "",
        trace_complete: bool = False,
        claim_semantic_pass: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> WorldcoinNormalizationResult:
        """Normalize a World Chain contract via the composed EVM frontend."""

        chain = _require_world_chain(chain_id)
        anchor = world_chain_anchor(chain)
        evm_result = self._evm.normalize_contract(
            chain_id=chain,
            address=address,
            runtime_bytecode=runtime_bytecode,
            block_number=block_number,
            code_epoch=code_epoch,
            creation_bytecode=creation_bytecode,
            compiler=compiler,
            compiler_version=compiler_version,
            compiler_flags=compiler_flags,
            libraries=libraries,
            constructor_args=constructor_args,
            metadata_policy=metadata_policy,
            abi=abi,
            network=anchor["network"],
            genesis_hash=anchor["genesis_hash"],
            storage=storage,
            previous_code_digest=previous_code_digest,
            trace_complete=trace_complete,
            claim_semantic_pass=claim_semantic_pass,
            attributes=attributes,
        )

        diagnostics = list(evm_result.diagnostics)
        diagnostics.append("composed_evm_frontend=smart-contracts.evm.frontend")
        diagnostics.append(f"settlement_layer={anchor['settlement_layer']}")
        diagnostics.append("bridge_trust_not_implied_by_contract_normalization")

        # Map EVM semantic status into Worldcoin status.
        if evm_result.semantic_pass_status is EVMSemanticPassStatus.PASS:
            pass_status = SemanticPassStatus.PASS
        elif evm_result.semantic_pass_status is EVMSemanticPassStatus.UNSUPPORTED:
            pass_status = SemanticPassStatus.UNSUPPORTED
        elif evm_result.semantic_pass_status is EVMSemanticPassStatus.FAIL_CLOSED:
            pass_status = SemanticPassStatus.FAIL_CLOSED
        else:
            pass_status = SemanticPassStatus.INCOMPLETE

        if evm_result.proxy.kind is ProxyKind.UNKNOWN:
            diagnostics.append("proxy layout unknown; upgrade authority untrusted")
        if evm_result.proxy.redeployment_risk in {
            RedeploymentRisk.SELFDESTRUCT_PRESENT,
            RedeploymentRisk.CODE_EPOCH_CHANGED,
        }:
            diagnostics.append(
                f"redeployment_risk={evm_result.proxy.redeployment_risk.value}"
            )
            if pass_status is SemanticPassStatus.PASS:
                pass_status = SemanticPassStatus.FAIL_CLOSED

        # Bridge trust is always stated for World Chain composition even when
        # no bridge observation is present — settlement depends on OP-stack.
        bridge_trust = default_bridge_trust_assumptions(
            settlement_layer=anchor["settlement_layer"]
        )
        diagnostics.append(
            "stated_bridge_trust="
            + ",".join(item.assumption_id for item in bridge_trust)
        )

        return WorldcoinNormalizationResult(
            composition_mode=CompositionMode.EVM_COMPOSED,
            chain_id=chain,
            network=anchor["network"],
            settlement_layer=anchor["settlement_layer"],
            evm_result=evm_result,
            bridge_trust=bridge_trust,
            pass_status=pass_status,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            attributes={
                "composes": "evm",
                "world_chain": True,
                **dict(attributes or {}),
            },
        )

    def normalize_verifier_contract(
        self,
        *,
        verifier_id: str,
        verifier_address: str,
        runtime_bytecode: bytes | str,
        external_nullifier: ExternalNullifier,
        chain_id: str | int,
        code_epoch: str = "",
        protocol_version: str = "4.0",
        verifier_kind: VerifierKind | str = VerifierKind.ON_CHAIN_WORLD_ID,
        block_number: int | None = None,
        storage: Mapping[str, str] | None = None,
        previous_code_digest: str = "",
        previous_verifier: WorldIDVerifierBinding | None = None,
        nullifier_commitment: str = "",
        verification_status: str = "verified",
        claim_payment_authorization: bool = False,
        claim_legal_identity: bool = False,
        claim_contract_safety: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> WorldcoinNormalizationResult:
        """Normalize a World ID verifier contract with domain and upgrade checks."""

        chain = _require_world_chain(chain_id)
        anchor = world_chain_anchor(chain)

        # Analyze verifier bytecode via EVM composition.
        composition = self.normalize_world_chain_contract(
            chain_id=chain,
            address=verifier_address,
            runtime_bytecode=runtime_bytecode,
            block_number=block_number,
            code_epoch=code_epoch,
            storage=storage,
            previous_code_digest=previous_code_digest,
            attributes=attributes,
        )
        assert composition.evm_result is not None
        evm_result = composition.evm_result

        impl_address = ""
        proxy_kind = ""
        if evm_result.proxy.implementation_address:
            impl_address = evm_result.proxy.implementation_address
            proxy_kind = (
                evm_result.proxy.kind.value
                if isinstance(evm_result.proxy.kind, ProxyKind)
                else str(evm_result.proxy.kind)
            )

        epoch_label = code_epoch.strip() if code_epoch else (
            evm_result.code_epoch.code_epoch
            or f"code:{evm_result.code_epoch.runtime_bytecode_digest}"
        )

        binding = self.bind_verifier(
            verifier_id=verifier_id,
            verifier_address=verifier_address,
            code_epoch=epoch_label,
            external_nullifier=external_nullifier,
            chain_id=chain,
            protocol_version=protocol_version,
            verifier_kind=verifier_kind,
            implementation_address=impl_address,
            implementation_code_digest=evm_result.code_epoch.runtime_bytecode_digest,
            proxy_kind=proxy_kind,
            network=anchor["network"],
            genesis_hash=anchor["genesis_hash"],
            block_number=block_number,
            attributes=attributes,
        )

        diagnostics = list(composition.diagnostics)
        diagnostics.append(f"verifier_id={verifier_id}")
        diagnostics.append(f"verifier_code_epoch={epoch_label}")
        diagnostics.append("proof_consumer_only=true")

        pass_status = composition.pass_status

        if previous_verifier is not None:
            upgrade_status = check_verifier_upgrade(previous_verifier, binding)
            if upgrade_status is SemanticPassStatus.FAIL_CLOSED:
                pass_status = SemanticPassStatus.FAIL_CLOSED
                diagnostics.append(
                    "verifier implementation code epoch changed; re-bind required"
                )
            elif upgrade_status is SemanticPassStatus.DOMAIN_MISMATCH:
                pass_status = SemanticPassStatus.DOMAIN_MISMATCH
                diagnostics.append(
                    "verifier address or chain mismatch vs previous binding"
                )
            else:
                diagnostics.append("verifier code epoch continuous with previous binding")

        verifier_trust = default_verifier_trust_assumptions(
            verifier_kind=binding.verifier_kind,
            code_epoch_pinned=True,
        )
        diagnostics.append(
            "stated_verifier_trust="
            + ",".join(item.assumption_id for item in verifier_trust)
        )

        proof_consumer: ProofConsumerBehavior | None = None
        replay: ReplayDomain | None = None
        if nullifier_commitment:
            replay = self.bind_replay_domain(
                external_nullifier=binding.external_nullifier,
                nullifier_commitment=nullifier_commitment,
                register=True,
            )
            proof_consumer = self.evaluate_proof_consumer(
                verification_status=verification_status,
                external_nullifier=binding.external_nullifier,
                nullifier_commitment=nullifier_commitment,
                verifier_binding=binding,
                claim_payment_authorization=claim_payment_authorization,
                claim_legal_identity=claim_legal_identity,
                claim_contract_safety=claim_contract_safety,
            )
            if proof_consumer.pass_status is not SemanticPassStatus.PASS:
                pass_status = proof_consumer.pass_status
            diagnostics.extend(proof_consumer.diagnostics)

        return WorldcoinNormalizationResult(
            composition_mode=CompositionMode.FULL_COMPOSITION
            if nullifier_commitment
            else CompositionMode.EVM_COMPOSED,
            chain_id=chain,
            network=anchor["network"],
            settlement_layer=anchor["settlement_layer"],
            evm_result=evm_result,
            verifier_binding=binding,
            external_nullifier=binding.external_nullifier,
            replay_domain=replay,
            proof_consumer=proof_consumer,
            verifier_trust=verifier_trust,
            bridge_trust=composition.bridge_trust,
            pass_status=pass_status,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            attributes={
                "composes": "evm",
                "world_id_verifier": True,
                **dict(attributes or {}),
            },
        )

    def normalize_bridge_observation(
        self,
        *,
        bridge_id: str,
        source_chain_id: str | int,
        destination_chain_id: str | int,
        direction: BridgeDirection | str = BridgeDirection.UNKNOWN,
        asset_symbol: str = "",
        amount_base_units: str = "",
        tx_hash_ref: str = "",
        code_epoch: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> WorldcoinNormalizationResult:
        """Normalize a bridge observation with every bridge trust assumption."""

        bridge = self.bind_bridge(
            bridge_id=bridge_id,
            source_chain_id=source_chain_id,
            destination_chain_id=destination_chain_id,
            direction=direction,
            asset_symbol=asset_symbol,
            amount_base_units=amount_base_units,
            tx_hash_ref=tx_hash_ref,
            code_epoch=code_epoch,
            attributes=attributes,
        )
        # Prefer World Chain side for result coordinates.
        if is_world_chain_id(bridge.source_chain_id):
            chain = bridge.source_chain_id
        else:
            chain = bridge.destination_chain_id
        anchor = world_chain_anchor(chain)
        diagnostics = [
            f"bridge_id={bridge_id}",
            "implies_world_id_proof=false",
            "implies_tx_auth=false",
            "stated_bridge_trust="
            + ",".join(item.assumption_id for item in bridge.trusted_assumptions),
        ]
        return WorldcoinNormalizationResult(
            composition_mode=CompositionMode.BRIDGE_ONLY,
            chain_id=chain,
            network=anchor["network"],
            settlement_layer=anchor["settlement_layer"],
            bridge=bridge,
            bridge_trust=bridge.trusted_assumptions,
            pass_status=SemanticPassStatus.PASS,
            diagnostics=tuple(diagnostics),
            attributes=dict(attributes or {}),
        )

    def detect_domain_confusion(
        self,
        intended: ExternalNullifier,
        observed: ExternalNullifier,
    ) -> SemanticPassStatus:
        """Adversarial fixture helper: detect domain/action confusion."""

        if intended.domain_key == observed.domain_key:
            return SemanticPassStatus.PASS
        # Same nullifier domain components partially overlapping is still mismatch.
        return SemanticPassStatus.DOMAIN_MISMATCH

    def bind_code_epoch(
        self,
        *,
        chain_id: str | int,
        address: str,
        runtime_bytecode: bytes | str,
        block_number: int | None = None,
        code_epoch: str = "",
        **kwargs: Any,
    ) -> EVMCodeEpoch:
        """Bind a World Chain code epoch via the composed EVM frontend."""

        chain = _require_world_chain(chain_id)
        anchor = world_chain_anchor(chain)
        return self._evm.bind_code_epoch(
            chain_id=chain,
            address=address,
            runtime_bytecode=runtime_bytecode,
            block_number=block_number,
            code_epoch=code_epoch,
            network=anchor["network"],
            genesis_hash=anchor["genesis_hash"],
            **kwargs,
        )


__all__ = [
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "CompositionMode",
    "WorldcoinContractFrontend",
    "WorldcoinNormalizationResult",
]
