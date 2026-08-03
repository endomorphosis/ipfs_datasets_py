"""Chain-specific security rule packs (CRYPTOIR-G310).

Common obligations are defined in :mod:`.security_rules`.  This module
**instantiates** them per chain namespace and adds chain-local rules only where
the corresponding frontend can supply semantic coverage.

Chain packs never silently reuse another chain's rule without an explicit
namespace match.  Wrong-chain evaluation yields
:attr:`~.security_rules.ApplicabilityStatus.NOT_APPLICABLE`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from .model import CryptoIRValidationError
from .security_rules import (
    SECURITY_RULE_PACK_VERSION,
    FormalTargetKind,
    ObligationCategory,
    SecurityRule,
    UnsupportedFallback,
    ViolationWitness,
    common_security_rules,
    iter_rule_ids,
)


# Reviewed chain namespace identifiers used by Crypto IR adapters/frontends.
CHAIN_NS_EIP155: Final[str] = "eip155"
CHAIN_NS_SOLANA: Final[str] = "solana"
CHAIN_NS_BIP122: Final[str] = "bip122"
CHAIN_NS_XRPL: Final[str] = "xrpl"
CHAIN_NS_WORLDCOIN: Final[str] = "worldcoin"

SUPPORTED_CHAIN_NAMESPACES: Final[tuple[str, ...]] = (
    CHAIN_NS_EIP155,
    CHAIN_NS_SOLANA,
    CHAIN_NS_BIP122,
    CHAIN_NS_XRPL,
    CHAIN_NS_WORLDCOIN,
)

CHAIN_RULE_PACK_VERSION: Final[str] = SECURITY_RULE_PACK_VERSION


def _witness(
    witness_id: str,
    description: str,
    *,
    path_summary: str = "",
) -> ViolationWitness:
    return ViolationWitness(
        witness_id=witness_id,
        description=description,
        path_summary=path_summary,
    )


def _chain_rule(
    *,
    rule_id: str,
    name: str,
    category: ObligationCategory,
    statement: str,
    formal_target: str,
    formal_target_kind: FormalTargetKind,
    chain_namespaces: Sequence[str],
    semantic_preconditions: Sequence[str],
    required_evidence: Sequence[str],
    witness: ViolationWitness,
    trusted_assumptions: Sequence[str] = (),
    unsupported_fallback: UnsupportedFallback = UnsupportedFallback.UNSUPPORTED,
    fact_id_templates: Sequence[str] = (),
    summary: str = "",
    version: str = "1.0.0",
) -> SecurityRule:
    return SecurityRule(
        rule_id=rule_id,
        version=version,
        name=name,
        category=category,
        statement=statement,
        formal_target=formal_target,
        formal_target_kind=formal_target_kind,
        semantic_preconditions=tuple(semantic_preconditions),
        required_evidence=tuple(required_evidence),
        violation_witness=witness,
        unsupported_fallback=unsupported_fallback,
        chain_namespaces=tuple(chain_namespaces),
        trusted_assumptions=tuple(trusted_assumptions),
        fact_id_templates=tuple(fact_id_templates),
        summary=summary,
        pack_version=CHAIN_RULE_PACK_VERSION,
    )


def _specialize_common(
    rule: SecurityRule,
    *,
    chain_namespaces: Sequence[str],
    rule_id_prefix: str,
    extra_semantic: Sequence[str] = (),
    extra_evidence: Sequence[str] = (),
    extra_assumptions: Sequence[str] = (),
) -> SecurityRule:
    """Bind a common rule to one or more chain namespaces."""

    if rule.chain_namespaces:
        raise CryptoIRValidationError(
            f"cannot specialize non-common rule {rule.rule_id!r}"
        )
    namespaces = tuple(chain_namespaces)
    if not namespaces:
        raise CryptoIRValidationError("chain specialization requires namespaces")
    suffix = rule.rule_id.removeprefix("common.")
    return SecurityRule(
        rule_id=f"{rule_id_prefix}.{suffix}",
        version=rule.version,
        name=f"{rule.name} ({','.join(namespaces)})",
        category=rule.category,
        statement=rule.statement,
        formal_target=rule.formal_target,
        formal_target_kind=rule.formal_target_kind,
        semantic_preconditions=tuple(
            dict.fromkeys((*rule.semantic_preconditions, *extra_semantic))
        ),
        required_evidence=tuple(
            dict.fromkeys((*rule.required_evidence, *extra_evidence))
        ),
        violation_witness=rule.violation_witness,
        unsupported_fallback=rule.unsupported_fallback,
        chain_namespaces=namespaces,
        trusted_assumptions=tuple(
            dict.fromkeys((*rule.trusted_assumptions, *extra_assumptions))
        ),
        fact_id_templates=rule.fact_id_templates,
        summary=rule.summary,
        pack_version=CHAIN_RULE_PACK_VERSION,
        attributes={
            "specialized_from": rule.rule_id,
            "chain_namespaces": list(namespaces),
        },
    )


# ---------------------------------------------------------------------------
# EVM / eip155
# ---------------------------------------------------------------------------


def evm_chain_rules() -> tuple[SecurityRule, ...]:
    """EVM-family rule pack (Ethereum, L2s sharing eip155 semantics)."""

    common = common_security_rules()
    specialized = tuple(
        _specialize_common(
            rule,
            chain_namespaces=(CHAIN_NS_EIP155,),
            rule_id_prefix="evm",
            extra_semantic=(
                ("storage_model",)
                if rule.category
                in {
                    ObligationCategory.AUTHORIZATION,
                    ObligationCategory.CALLBACK_REENTRANCY,
                    ObligationCategory.UPGRADE,
                }
                else ()
            ),
            extra_evidence=(
                ("bytecode_or_source", "call_graph")
                if rule.category
                in {
                    ObligationCategory.AUTHORIZATION,
                    ObligationCategory.CALLBACK_REENTRANCY,
                }
                else ()
            ),
        )
        for rule in common
        if rule.category
        not in {
            # CPI is Solana-specific; EVM uses callback/reentrancy instead.
            ObligationCategory.CPI,
        }
    )
    local = (
        _chain_rule(
            rule_id="evm.delegatecall.context",
            name="Delegatecall context integrity",
            category=ObligationCategory.AUTHORIZATION,
            statement=(
                "DELEGATECALL targets execute only under declared proxy/"
                "library bindings and cannot silently rewrite storage of an "
                "unrelated implementation epoch."
            ),
            formal_target=(
                "delegatecall e implies binding(e) in declared_proxy_set and "
                "storage_epoch matches expected implementation"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_EIP155,),
            semantic_preconditions=(
                "control_flow",
                "storage_model",
                "proxy_binding",
            ),
            required_evidence=(
                "delegatecall_edges",
                "proxy_binding",
                "code_epoch",
            ),
            witness=_witness(
                "wit:evm-delegatecall",
                "A DELEGATECALL edge targets an unbound implementation or "
                "mutates storage outside the declared proxy binding.",
                path_summary="unbound delegatecall",
            ),
            trusted_assumptions=("evm.proxy_layout_declared",),
            fact_id_templates=("edge:*", "epoch:*"),
            summary="EVM-specific delegatecall / proxy storage obligation",
        ),
        _chain_rule(
            rule_id="evm.approval.drain_bound",
            name="ERC-20 approval drain bound",
            category=ObligationCategory.ALLOWANCE,
            statement=(
                "Token approvals granted by a user intent cannot be spent beyond "
                "the approved amount by any spender in the modeled call graph."
            ),
            formal_target=(
                "sum(allowance_spend by spender) <= approved_amount for each "
                "owner/spender/token triple"
            ),
            formal_target_kind=FormalTargetKind.SMT_LIB,
            chain_namespaces=(CHAIN_NS_EIP155,),
            semantic_preconditions=("asset_effects", "control_flow"),
            required_evidence=(
                "approve_logs_or_effects",
                "transferFrom_effects",
                "spender_set",
            ),
            witness=_witness(
                "wit:evm-approval-drain",
                "Spenders extract more value than the remaining ERC-20 allowance.",
            ),
            fact_id_templates=("effect:*",),
        ),
    )
    return specialized + local


# ---------------------------------------------------------------------------
# Solana
# ---------------------------------------------------------------------------


def solana_chain_rules() -> tuple[SecurityRule, ...]:
    """Solana program rule pack."""

    common = common_security_rules()
    specialized = tuple(
        _specialize_common(
            rule,
            chain_namespaces=(CHAIN_NS_SOLANA,),
            rule_id_prefix="solana",
            extra_semantic=(
                ("account_privileges", "pda_constraints")
                if rule.category
                in {
                    ObligationCategory.AUTHORIZATION,
                    ObligationCategory.CPI,
                }
                else ()
            ),
            extra_evidence=(
                ("account_metas", "owner_checks")
                if rule.category
                in {
                    ObligationCategory.AUTHORIZATION,
                    ObligationCategory.CPI,
                }
                else ()
            ),
        )
        for rule in common
        if rule.category
        not in {
            # EVM reentrancy label is separate; Solana uses CPI + reentrancy
            # when the frontend models reentrant callbacks.
        }
    )
    local = (
        _chain_rule(
            rule_id="solana.signer.owner_writable",
            name="Signer, owner, and writable account checks",
            category=ObligationCategory.AUTHORIZATION,
            statement=(
                "Every instruction account that is signed, writable, or "
                "owner-constrained satisfies the declared privilege and owner "
                "checks before mutation."
            ),
            formal_target=(
                "for each account meta m: "
                "signed(m)=>is_signer(m) and writable(m)=>declared_writable(m) "
                "and owner_check(m) when required"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_SOLANA,),
            semantic_preconditions=(
                "account_privileges",
                "control_flow",
                "pda_constraints",
            ),
            required_evidence=(
                "account_metas",
                "signer_flags",
                "owner_program_ids",
                "pda_seeds",
            ),
            witness=_witness(
                "wit:solana-missing-signer",
                "An instruction mutates an account without required signer, "
                "owner, or writable constraints.",
            ),
            fact_id_templates=("edge:*", "account:*"),
        ),
        _chain_rule(
            rule_id="solana.lamport.conservation",
            name="Lamport and token account conservation",
            category=ObligationCategory.VALUE_CONSERVATION,
            statement=(
                "Lamports and SPL token balances conserved across instruction "
                "and CPI graphs modulo declared fees and explicit mint/burn."
            ),
            formal_target=(
                "sum(lamports_in) = sum(lamports_out) + fees and "
                "token_accounts conserve amount per mint"
            ),
            formal_target_kind=FormalTargetKind.SMT_LIB,
            chain_namespaces=(CHAIN_NS_SOLANA,),
            semantic_preconditions=("asset_effects", "control_flow"),
            required_evidence=(
                "lamport_deltas",
                "token_account_deltas",
                "fee_schedule",
            ),
            witness=_witness(
                "wit:solana-lamport-leak",
                "Lamports or token amounts are created or destroyed without "
                "declared mint/burn authority.",
            ),
            fact_id_templates=("effect:*",),
        ),
    )
    return specialized + local


# ---------------------------------------------------------------------------
# Bitcoin / bip122
# ---------------------------------------------------------------------------


def bitcoin_chain_rules() -> tuple[SecurityRule, ...]:
    """Bitcoin Script / Tapscript / Miniscript rule pack."""

    relevant = {
        ObligationCategory.AUTHORIZATION,
        ObligationCategory.VALUE_CONSERVATION,
        ObligationCategory.REPLAY,
        ObligationCategory.TIMELOCK,
        ObligationCategory.INTENT_EFFECT_EQUALITY,
        ObligationCategory.RESOURCE_BOUNDS,
    }
    specialized = tuple(
        _specialize_common(
            rule,
            chain_namespaces=(CHAIN_NS_BIP122,),
            rule_id_prefix="bitcoin",
            extra_semantic=(
                ("spend_paths", "sighash")
                if rule.category
                in {ObligationCategory.AUTHORIZATION, ObligationCategory.TIMELOCK}
                else ()
            ),
            extra_evidence=(
                ("script_or_miniscript", "prevouts")
                if rule.category is ObligationCategory.AUTHORIZATION
                else ()
            ),
        )
        for rule in common_security_rules()
        if rule.category in relevant
    )
    local = (
        _chain_rule(
            rule_id="bitcoin.spend_path.unintended",
            name="Unintended spend path prevention",
            category=ObligationCategory.AUTHORIZATION,
            statement=(
                "Only declared Tapscript leaves / Miniscript branches that "
                "satisfy the policy may spend a UTXO under the bound sighash."
            ),
            formal_target=(
                "spend_path p succeeds implies p in declared_policy_paths and "
                "sighash_commits(p, intended_fields)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_BIP122,),
            semantic_preconditions=("spend_paths", "sighash", "control_flow"),
            required_evidence=(
                "tapscript_leaves_or_script",
                "control_block_or_redeem",
                "sighash_type",
                "prevouts",
            ),
            witness=_witness(
                "wit:bitcoin-alt-spend",
                "An alternate script path or weak sighash spends value outside "
                "the declared policy.",
                path_summary="unintended spend_path",
            ),
            trusted_assumptions=("bitcoin.policy_descriptor_complete",),
            fact_id_templates=("edge:*",),
        ),
        _chain_rule(
            rule_id="bitcoin.timelock.maturity",
            name="nLockTime / nSequence / CLTV / CSV maturity",
            category=ObligationCategory.TIMELOCK,
            statement=(
                "Timelocked spends are enabled only when absolute/relative "
                "locktime conditions encoded in the script and transaction "
                "fields are satisfied."
            ),
            formal_target=(
                "spend enabled iff cltv_csv_and_tx_locktime_satisfied"
            ),
            formal_target_kind=FormalTargetKind.TEMPORAL,
            chain_namespaces=(CHAIN_NS_BIP122,),
            semantic_preconditions=("workflow_time", "spend_paths"),
            required_evidence=(
                "locktime_fields",
                "script_timelock_ops",
                "chain_height_or_mtp",
            ),
            witness=_witness(
                "wit:bitcoin-timelock-bypass",
                "A spend succeeds before absolute/relative timelock maturity.",
            ),
            fact_id_templates=("edge:*",),
        ),
    )
    return specialized + local


# ---------------------------------------------------------------------------
# XRPL
# ---------------------------------------------------------------------------


def xrpl_chain_rules() -> tuple[SecurityRule, ...]:
    """XRPL native-ledger rule pack."""

    relevant = {
        ObligationCategory.AUTHORIZATION,
        ObligationCategory.VALUE_CONSERVATION,
        ObligationCategory.MINT_BURN_TRANSFER,
        ObligationCategory.REPLAY,
        ObligationCategory.UPGRADE,
        ObligationCategory.INTENT_EFFECT_EQUALITY,
        ObligationCategory.TIMELOCK,
        ObligationCategory.RESOURCE_BOUNDS,
    }
    specialized = tuple(
        _specialize_common(
            rule,
            chain_namespaces=(CHAIN_NS_XRPL,),
            rule_id_prefix="xrpl",
            extra_semantic=(
                ("ledger_objects",)
                if rule.category
                in {
                    ObligationCategory.AUTHORIZATION,
                    ObligationCategory.VALUE_CONSERVATION,
                }
                else ()
            ),
        )
        for rule in common_security_rules()
        if rule.category in relevant
    )
    local = (
        _chain_rule(
            rule_id="xrpl.sequence.replay",
            name="Sequence and ticket replay binding",
            category=ObligationCategory.REPLAY,
            statement=(
                "Each accepted transaction consumes a unique account sequence "
                "or ticket and is bound to the ledger network id."
            ),
            formal_target=(
                "accept(tx) once per (account, sequence_or_ticket, network_id)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_XRPL,),
            semantic_preconditions=("replay_domain", "ledger_objects"),
            required_evidence=(
                "account_sequence",
                "ticket_if_any",
                "network_id",
            ),
            witness=_witness(
                "wit:xrpl-sequence-replay",
                "A transaction is accepted twice or without consuming sequence/"
                "ticket on the bound network.",
            ),
            fact_id_templates=("tx:*",),
        ),
        _chain_rule(
            rule_id="xrpl.issuer.freeze_clawback",
            name="Issuer freeze and clawback authority",
            category=ObligationCategory.MINT_BURN_TRANSFER,
            statement=(
                "Freeze and clawback transitions occur only for issuers with "
                "declared flags and never silently seize unrelated trust lines."
            ),
            formal_target=(
                "freeze_or_clawback e implies issuer_flag_enabled and "
                "targets_declared_trust_line(e)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_XRPL,),
            semantic_preconditions=("asset_effects", "ledger_objects"),
            required_evidence=(
                "issuer_flags",
                "trust_line_ids",
                "clawback_enablement",
            ),
            witness=_witness(
                "wit:xrpl-clawback",
                "Freeze or clawback applies without issuer authority or to an "
                "undeclared trust line.",
            ),
            fact_id_templates=("effect:*",),
        ),
    )
    return specialized + local


# ---------------------------------------------------------------------------
# Worldcoin / World Chain
# ---------------------------------------------------------------------------


def worldcoin_chain_rules() -> tuple[SecurityRule, ...]:
    """Worldcoin / World ID / World Chain composition rule pack.

    World Chain reuses EVM obligations and adds identity-proof domain binding.
    A valid World ID proof never implies payment authorization by itself.
    """

    # Reuse EVM specialization under both eip155 (shared VM) and worldcoin ns.
    evm_like = tuple(
        _specialize_common(
            rule,
            chain_namespaces=(CHAIN_NS_WORLDCOIN, CHAIN_NS_EIP155),
            rule_id_prefix="worldcoin",
            extra_semantic=("world_id_binding",)
            if rule.category is ObligationCategory.REPLAY
            else (),
            extra_evidence=(
                ("external_nullifier", "action_id")
                if rule.category is ObligationCategory.REPLAY
                else ()
            ),
            extra_assumptions=(
                ("worldcoin.verifier_code_epoch_pinned",)
                if rule.category
                in {ObligationCategory.REPLAY, ObligationCategory.UPGRADE}
                else ()
            ),
        )
        for rule in common_security_rules()
        if rule.category
        not in {
            ObligationCategory.CPI,
        }
    )
    local = (
        _chain_rule(
            rule_id="worldcoin.nullifier.action_binding",
            name="World ID nullifier and action binding",
            category=ObligationCategory.REPLAY,
            statement=(
                "A World ID proof is bound to chain, external nullifier, and "
                "action; the same nullifier cannot authorize a different action "
                "or payment."
            ),
            formal_target=(
                "verify(proof) implies bind(chain, external_nullifier, action) "
                "and nullifier unused in that domain"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_WORLDCOIN,),
            semantic_preconditions=(
                "world_id_binding",
                "replay_domain",
                "identity_binding",
            ),
            required_evidence=(
                "verifier_code_epoch",
                "external_nullifier",
                "action_id",
                "nullifier_hash",
                "chain_id",
            ),
            witness=_witness(
                "wit:worldcoin-nullifier-reuse",
                "A nullifier is accepted for a different action/domain or a "
                "proof is treated as payment authorization.",
            ),
            trusted_assumptions=(
                "worldcoin.verifier_code_epoch_pinned",
                "worldcoin.proof_not_payment_authority",
            ),
            fact_id_templates=("binding:*", "epoch:*"),
            summary=(
                "World ID proof domain binding; never elevates to payment auth"
            ),
        ),
        _chain_rule(
            rule_id="worldcoin.proof.not_payment",
            name="Identity proof is not payment authorization",
            category=ObligationCategory.AUTHORIZATION,
            statement=(
                "Acceptance of a valid World ID proof does not by itself "
                "authorize asset transfers, approvals, or contract upgrades."
            ),
            formal_target=(
                "world_id_verified(p) does not imply authorized_transfer(p) "
                "or authorized_upgrade(p)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            chain_namespaces=(CHAIN_NS_WORLDCOIN,),
            semantic_preconditions=(
                "world_id_binding",
                "asset_effects",
                "privileges",
            ),
            required_evidence=(
                "proof_verification_result",
                "transfer_or_upgrade_effects",
                "separate_auth_path",
            ),
            witness=_witness(
                "wit:worldcoin-proof-as-payment",
                "An asset transfer or upgrade is authorized solely by World ID "
                "proof acceptance without a separate privilege grant.",
            ),
            trusted_assumptions=("worldcoin.proof_not_payment_authority",),
            fact_id_templates=("effect:*", "binding:*"),
        ),
    )
    return evm_like + local


# ---------------------------------------------------------------------------
# Pack registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChainRulePack:
    """Versioned catalog of rules for one primary chain namespace."""

    chain_namespace: str
    pack_version: str
    rules: tuple[SecurityRule, ...]
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.chain_namespace, str) or not self.chain_namespace.strip():
            raise CryptoIRValidationError("chain_namespace must be a non-empty string")
        if self.chain_namespace != self.chain_namespace.strip():
            raise CryptoIRValidationError(
                "chain_namespace must not have surrounding whitespace"
            )
        if not isinstance(self.pack_version, str) or not self.pack_version:
            raise CryptoIRValidationError("pack_version must be a non-empty string")
        if not isinstance(self.rules, tuple):
            object.__setattr__(self, "rules", tuple(self.rules))
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise CryptoIRValidationError(
                f"duplicate rule ids in pack for {self.chain_namespace}"
            )
        for rule in self.rules:
            if not isinstance(rule, SecurityRule):
                raise CryptoIRValidationError("pack rules must be SecurityRule")
            if not rule.supports_chain(self.chain_namespace):
                raise CryptoIRValidationError(
                    f"rule {rule.rule_id} does not support pack namespace "
                    f"{self.chain_namespace}"
                )

    def rule_ids(self) -> tuple[str, ...]:
        return iter_rule_ids(self.rules)

    def get(self, rule_id: str) -> SecurityRule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise CryptoIRValidationError(
            f"unknown rule {rule_id!r} in pack {self.chain_namespace}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "chain_namespace": self.chain_namespace,
            "pack_version": self.pack_version,
            "rule_ids": list(self.rule_ids()),
            "rules": [rule.to_dict() for rule in self.rules],
            "summary": self.summary,
        }


def chain_rule_pack(chain_namespace: str) -> ChainRulePack:
    """Return the reviewed rule pack for *chain_namespace* or fail closed."""

    if not isinstance(chain_namespace, str) or not chain_namespace.strip():
        raise CryptoIRValidationError("chain_namespace must be a non-empty string")
    namespace = chain_namespace.strip()
    builders = {
        CHAIN_NS_EIP155: (
            evm_chain_rules,
            "EVM / eip155 security obligations",
        ),
        CHAIN_NS_SOLANA: (
            solana_chain_rules,
            "Solana program security obligations",
        ),
        CHAIN_NS_BIP122: (
            bitcoin_chain_rules,
            "Bitcoin Script/Tapscript security obligations",
        ),
        CHAIN_NS_XRPL: (
            xrpl_chain_rules,
            "XRPL native-ledger security obligations",
        ),
        CHAIN_NS_WORLDCOIN: (
            worldcoin_chain_rules,
            "Worldcoin / World ID / World Chain security obligations",
        ),
    }
    try:
        builder, summary = builders[namespace]
    except KeyError as exc:
        raise CryptoIRValidationError(
            f"no chain rule pack for namespace {namespace!r}; "
            f"supported={list(SUPPORTED_CHAIN_NAMESPACES)}"
        ) from exc
    return ChainRulePack(
        chain_namespace=namespace,
        pack_version=CHAIN_RULE_PACK_VERSION,
        rules=builder(),
        summary=summary,
    )


def all_chain_rule_packs() -> tuple[ChainRulePack, ...]:
    """Return every supported chain pack in stable namespace order."""

    return tuple(chain_rule_pack(ns) for ns in SUPPORTED_CHAIN_NAMESPACES)


def all_security_rules() -> tuple[SecurityRule, ...]:
    """Common rules plus every chain-local rule (deduplicated by rule_id)."""

    by_id: dict[str, SecurityRule] = {}
    for rule in common_security_rules():
        by_id[rule.rule_id] = rule
    for pack in all_chain_rule_packs():
        for rule in pack.rules:
            by_id[rule.rule_id] = rule
    return tuple(by_id[key] for key in sorted(by_id))


def rules_for_chain(chain_namespace: str) -> tuple[SecurityRule, ...]:
    """Return common rules specialized or applicable to *chain_namespace*.

    Includes:

    * common (chain-neutral) rules that apply to every namespace
    * the dedicated chain pack for *chain_namespace*
    """

    pack = chain_rule_pack(chain_namespace)
    # Common rules remain available as the cross-chain baseline.
    common = common_security_rules()
    by_id: dict[str, SecurityRule] = {rule.rule_id: rule for rule in common}
    for rule in pack.rules:
        by_id[rule.rule_id] = rule
    return tuple(by_id[key] for key in sorted(by_id))


def assert_no_silent_cross_chain_apply(
    rule: SecurityRule,
    chain_namespace: str,
) -> None:
    """Fail closed when *rule* would be wrong-chain for *chain_namespace*.

    Convenience guard for frontends that must never apply Solana CPI rules to
    Bitcoin models (etc.).
    """

    if not rule.supports_chain(chain_namespace):
        raise CryptoIRValidationError(
            f"rule {rule.rule_id} is not applicable to chain namespace "
            f"{chain_namespace!r} (no silent cross-chain apply)"
        )


__all__ = [
    "CHAIN_NS_BIP122",
    "CHAIN_NS_EIP155",
    "CHAIN_NS_SOLANA",
    "CHAIN_NS_WORLDCOIN",
    "CHAIN_NS_XRPL",
    "CHAIN_RULE_PACK_VERSION",
    "SUPPORTED_CHAIN_NAMESPACES",
    "ChainRulePack",
    "all_chain_rule_packs",
    "all_security_rules",
    "assert_no_silent_cross_chain_apply",
    "bitcoin_chain_rules",
    "chain_rule_pack",
    "evm_chain_rules",
    "rules_for_chain",
    "solana_chain_rules",
    "worldcoin_chain_rules",
    "xrpl_chain_rules",
]
