"""CRYPTOIR-G250 Bitcoin Script, Tapscript, Miniscript, and PSBT semantics.

Acceptance coverage:

* Stack and spending-path semantics bind exact prevouts, amounts, script
  versions, witness/control commitments, sighash flags, locktime/sequence,
  policy keys, and resource bounds;
* hidden or unavailable branches remain incomplete;
* descriptor/miniscript policy equality is proven or explicitly unknown;
* fixtures for alternative-spend, weak-sighash, timelock, control-block, and
  descriptor-mismatch;
* spend conditions are modeled (not account contracts).
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.smart_contracts.artifacts import bytes_digest
from ipfs_datasets_py.processors.smart_contracts.bitcoin import (
    AnalysisMode,
    BitcoinScriptFrontend,
    LeafAvailability,
    MiniscriptPolicy,
    PolicyEquivalenceStatus,
    ScriptForm,
    ScriptProgram,
    ScriptVersion,
    SemanticPassStatus,
    SighashCommitment,
    SighashFlag,
    SpendPathKind,
    TapscriptLeaf,
    classify_script_form,
    decode_script,
    incomplete_spend_never_passes,
    parse_control_block,
    parse_descriptor,
    parse_miniscript,
    tapleaf_hash,
)
from ipfs_datasets_py.processors.smart_contracts.errors import (
    InvalidRequestError,
    ResourceLimitError,
)


# ---------------------------------------------------------------------------
# Fixtures / golden scripts (offline)
# ---------------------------------------------------------------------------

# P2PKH: OP_DUP OP_HASH160 <20 zero bytes> OP_EQUALVERIFY OP_CHECKSIG
P2PKH = bytes.fromhex("76a914" + "11" * 20 + "88ac")

# P2WPKH: OP_0 <20>
P2WPKH = bytes.fromhex("0014" + "22" * 20)

# P2WSH: OP_0 <32>
P2WSH = bytes.fromhex("0020" + "33" * 32)

# P2TR: OP_1 <32>
P2TR = bytes.fromhex("5120" + "44" * 32)

# P2SH: OP_HASH160 <20> OP_EQUAL
P2SH = bytes.fromhex("a914" + "55" * 20 + "87")

# Multisig 2-of-3 bare (compressed pubkeys as 33-byte pushes of 0x02||zeros)
_KEY1 = bytes([0x21, 0x02] + [0x01] * 32)
_KEY2 = bytes([0x21, 0x02] + [0x02] * 32)
_KEY3 = bytes([0x21, 0x02] + [0x03] * 32)
MULTISIG_2OF3 = bytes([0x52]) + _KEY1 + _KEY2 + _KEY3 + bytes([0x53, 0xAE])

# CSV relative timelock: OP_10 OP_CHECKSEQUENCEVERIFY OP_DROP OP_DUP ...
CSV_SCRIPT = bytes.fromhex("5ab275") + P2PKH[0:]  # OP_10 CSV DROP + p2pkh tail-ish
# Cleaner: <100> CSV DROP <pubkey> CHECKSIG — use OP_1 CSV DROP + minimal
CSV_ONLY = bytes.fromhex("51b27551ac")  # OP_1 CSV DROP OP_1 CHECKSIG (structural)

# CLTV: OP_1 OP_CHECKLOCKTIMEVERIFY OP_DROP OP_1 OP_CHECKSIG
CLTV_ONLY = bytes.fromhex("51b17551ac")

# Hashlock: OP_SHA256 <32> OP_EQUAL
HASHLOCK = bytes.fromhex("a820" + "66" * 32 + "87")

# Unknown non-push opcode 0xFF then OP_0 — not in the closed known set.
UNSUPPORTED_SCRIPT = bytes.fromhex("ff00")

TXID = "a" * 64
INTERNAL_KEY = bytes.fromhex("11" * 32)
OUTPUT_KEY = bytes.fromhex("22" * 32)

# Simple tapscript: OP_1 OP_CHECKSIG (not realistic key, structural)
TAP_LEAF_SCRIPT = bytes.fromhex("51ac")


@pytest.fixture
def frontend() -> BitcoinScriptFrontend:
    return BitcoinScriptFrontend()


# ---------------------------------------------------------------------------
# AST symbols / public surface
# ---------------------------------------------------------------------------


def test_ast_symbols_are_exportable() -> None:
    """AST query: BitcoinScriptFrontend ScriptProgram TapscriptLeaf MiniscriptPolicy SighashCommitment."""

    assert BitcoinScriptFrontend is not None
    assert ScriptProgram is not None
    assert TapscriptLeaf is not None
    assert MiniscriptPolicy is not None
    assert SighashCommitment is not None


def test_frontend_identity(frontend: BitcoinScriptFrontend) -> None:
    assert frontend.frontend_id == "smart-contracts.bitcoin.frontend"
    assert frontend.version == "1.0.0"


# ---------------------------------------------------------------------------
# Script classification and decode
# ---------------------------------------------------------------------------


def test_classify_standard_forms() -> None:
    assert classify_script_form(P2PKH) is ScriptForm.P2PKH
    assert classify_script_form(P2WPKH) is ScriptForm.P2WPKH
    assert classify_script_form(P2WSH) is ScriptForm.P2WSH
    assert classify_script_form(P2TR) is ScriptForm.P2TR
    assert classify_script_form(P2SH) is ScriptForm.P2SH
    assert classify_script_form(MULTISIG_2OF3) is ScriptForm.MULTISIG
    assert classify_script_form(HASHLOCK) is ScriptForm.HASHLOCK
    assert classify_script_form(CLTV_ONLY) is ScriptForm.TIMELOCK


def test_decode_p2pkh_program() -> None:
    program = decode_script(P2PKH)
    assert program.form is ScriptForm.P2PKH
    assert program.version is ScriptVersion.LEGACY
    assert program.fully_decoded
    assert program.op_count == 5
    assert program.script_digest == bytes_digest(P2PKH)
    assert not program.unsupported_opcodes
    assert program.content_digest().startswith("sha256:")


def test_decode_segwit_and_taproot_versions() -> None:
    wpkh = decode_script(P2WPKH)
    assert wpkh.form is ScriptForm.P2WPKH
    assert wpkh.witness_version == 0
    assert wpkh.is_segwit

    tr = decode_script(P2TR)
    assert tr.form is ScriptForm.P2TR
    assert tr.witness_version == 1
    assert tr.is_taproot


def test_resource_bounds_script_bytes(frontend: BitcoinScriptFrontend) -> None:
    tiny = BitcoinScriptFrontend(max_script_bytes=4)
    with pytest.raises(ResourceLimitError):
        tiny.decode_locking_script(P2PKH)


def test_resource_bounds_ops() -> None:
    # Many OP_NOP
    script = bytes([0x61] * 10)
    with pytest.raises(ResourceLimitError):
        decode_script(script, max_ops=5)


# ---------------------------------------------------------------------------
# Prevout / amount / stack binding
# ---------------------------------------------------------------------------


def test_prevout_binds_exact_amount_and_script(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID,
        vout=1,
        value_sats=50_000_000,
        script_pubkey=P2WPKH,
    )
    assert prev.outpoint_key == f"{TXID}:1"
    assert prev.value_sats == 50_000_000
    assert prev.script_form is ScriptForm.P2WPKH
    assert prev.known
    assert prev.script_pubkey_digest == bytes_digest(P2WPKH)
    payload = prev.to_dict()
    assert payload["value_sats"] == 50_000_000
    assert "account" not in payload  # not an account model


def test_spend_analysis_requires_prevout_for_pass(
    frontend: BitcoinScriptFrontend,
) -> None:
    # Without prevout, claim_pass fails closed / incomplete.
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        script_pubkey=P2PKH,
        claim_pass=True,
    )
    assert result.semantic_pass_status in {
        SemanticPassStatus.INCOMPLETE,
        SemanticPassStatus.FAIL_CLOSED,
    }
    assert result.prevout is None


def test_spend_analysis_pass_with_bound_prevout(
    frontend: BitcoinScriptFrontend,
) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=100_000, script_pubkey=P2PKH
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        network="mainnet",
        prevout=prev,
        script_pubkey=P2PKH,
        sighash_type=int(SighashFlag.ALL),
        sequence=0xFFFFFFFF,
        locktime=0,
        claim_pass=True,
    )
    assert result.semantic_pass_status is SemanticPassStatus.PASS
    assert result.analysis_mode is AnalysisMode.SPEND_PATH
    assert result.stack is not None
    assert result.stack.prevout is not None
    assert result.stack.prevout.value_sats == 100_000
    assert result.is_pass


# ---------------------------------------------------------------------------
# Weak sighash
# ---------------------------------------------------------------------------


def test_weak_sighash_never_passes(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=1_000, script_pubkey=P2PKH
    )
    for flag in (
        int(SighashFlag.NONE),
        int(SighashFlag.SINGLE),
        int(SighashFlag.NONE) | int(SighashFlag.ANYONECANPAY),
        int(SighashFlag.ALL) | int(SighashFlag.ANYONECANPAY),
    ):
        result = frontend.analyze_spend(
            chain_id="bitcoin-mainnet",
            prevout=prev,
            script_pubkey=P2PKH,
            sighash_type=flag,
            claim_pass=True,
        )
        assert result.semantic_pass_status in {
            SemanticPassStatus.INCOMPLETE,
            SemanticPassStatus.FAIL_CLOSED,
        }, flag
        assert result.stack is not None
        assert result.stack.sighash is not None
        assert result.stack.sighash.is_weak
        assert any("weak sighash" in d for d in result.diagnostics)


def test_sighash_all_not_weak(frontend: BitcoinScriptFrontend) -> None:
    commitment = frontend.bind_sighash(
        sighash_type=int(SighashFlag.ALL),
        input_index=0,
    )
    assert not commitment.is_weak
    assert commitment.commitment_digest.startswith("sha256:")


# ---------------------------------------------------------------------------
# Timelock
# ---------------------------------------------------------------------------


def test_csv_timelock_extraction_and_satisfaction(
    frontend: BitcoinScriptFrontend,
) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=5_000, script_pubkey=CSV_ONLY
    )
    # Sequence too low → unsatisfied.
    unsat = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=CSV_ONLY,
        sequence=0,  # relative lock not met for OP_1 CSV
        claim_pass=True,
    )
    assert unsat.stack is not None
    assert unsat.stack.timelocks
    assert unsat.stack.timelocks[0].kind == "csv"
    # value from OP_1 is 1; sequence 0 fails
    assert unsat.stack.timelocks[0].satisfied is False
    assert unsat.semantic_pass_status is SemanticPassStatus.FAIL_CLOSED

    sat = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=CSV_ONLY,
        sequence=1,
        sighash_type=int(SighashFlag.ALL),
        claim_pass=True,
    )
    assert sat.stack is not None
    assert sat.stack.timelocks[0].satisfied is True
    assert sat.semantic_pass_status is SemanticPassStatus.PASS


def test_cltv_timelock(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=2, value_sats=2_000, script_pubkey=CLTV_ONLY
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=CLTV_ONLY,
        locktime=0,
        claim_pass=False,
    )
    assert result.stack is not None
    assert any(t.kind == "cltv" for t in result.stack.timelocks)


# ---------------------------------------------------------------------------
# Alternative spend paths
# ---------------------------------------------------------------------------


def test_alternative_spend_paths_recorded(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=9_000, script_pubkey=P2SH
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=P2SH,
        redeem_script=MULTISIG_2OF3,
        alternate_scripts=[HASHLOCK, CSV_ONLY],
        claim_pass=False,
    )
    path_ids = {p.path_id for p in result.spending_paths}
    assert "primary" in path_ids
    assert "alternate:0" in path_ids
    assert "alternate:1" in path_ids
    assert len(result.spending_paths) >= 3
    # Alternates remain available but incomplete without full witness.
    alts = [p for p in result.spending_paths if p.path_id.startswith("alternate:")]
    assert all(p.available for p in alts)


# ---------------------------------------------------------------------------
# Tapscript / control block / hidden branches
# ---------------------------------------------------------------------------


def test_control_block_parse_and_leaf(frontend: BitcoinScriptFrontend) -> None:
    leaf = frontend.bind_tapscript_leaf(TAP_LEAF_SCRIPT)
    assert leaf.leaf_version == 0xC0
    assert leaf.availability is LeafAvailability.AVAILABLE
    assert leaf.program is not None
    assert leaf.leaf_hash.startswith("sha256:")
    # Control block: leaf_ver|parity + internal key + one merkle node
    control_raw = bytes([0xC0]) + INTERNAL_KEY + bytes.fromhex("aa" * 32)
    control = frontend.parse_control_block(control_raw)
    assert control.complete
    assert control.depth == 1
    assert control.internal_key_hex == INTERNAL_KEY.hex()
    assert control.leaf_version == 0xC0

    commitment = frontend.bind_taproot(
        internal_key=INTERNAL_KEY,
        output_key=OUTPUT_KEY,
        revealed_leaves=[leaf],
        control_block=control,
        spend_path=SpendPathKind.SCRIPT_PATH,
    )
    assert commitment.spend_path is SpendPathKind.SCRIPT_PATH
    assert commitment.commitment_complete
    assert not commitment.hidden_branches


def test_hidden_tap_branch_incomplete(frontend: BitcoinScriptFrontend) -> None:
    leaf = frontend.bind_tapscript_leaf(
        TAP_LEAF_SCRIPT, availability=LeafAvailability.HIDDEN
    )
    assert leaf.is_hidden
    commitment = frontend.bind_taproot(
        internal_key=INTERNAL_KEY,
        revealed_leaves=[leaf],
        hidden_branch_digests=["sha256:" + "bb" * 32],
        spend_path=SpendPathKind.SCRIPT_PATH,
    )
    assert commitment.hidden_branches
    assert not commitment.commitment_complete
    with pytest.raises(InvalidRequestError):
        # Cannot mark complete with hidden branches
        from ipfs_datasets_py.processors.smart_contracts.bitcoin import (
            TaprootCommitment,
        )

        TaprootCommitment(
            internal_key_hex=INTERNAL_KEY.hex(),
            hidden_branches=("x",),
            commitment_complete=True,
        )

    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=1_000, script_pubkey=P2TR
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=P2TR,
        taproot=commitment,
        claim_pass=True,
    )
    assert result.semantic_pass_status in {
        SemanticPassStatus.INCOMPLETE,
        SemanticPassStatus.FAIL_CLOSED,
    }
    assert any(
        p.path_id == "taproot:hidden" and not p.available
        for p in result.spending_paths
    )


def test_malformed_control_block_incomplete(frontend: BitcoinScriptFrontend) -> None:
    # 34 bytes → not 33 + 32*k
    raw = bytes([0xC0]) + INTERNAL_KEY + b"\x00"
    control = parse_control_block(raw)
    assert not control.complete
    assert control.attributes.get("malformed_length") is True


def test_tapleaf_hash_deterministic() -> None:
    h1 = tapleaf_hash(TAP_LEAF_SCRIPT)
    h2 = tapleaf_hash(TAP_LEAF_SCRIPT)
    assert h1 == h2
    assert len(h1) == 32


# ---------------------------------------------------------------------------
# Miniscript / descriptors / equality
# ---------------------------------------------------------------------------


def test_miniscript_parse_and_keys(frontend: BitcoinScriptFrontend) -> None:
    policy = frontend.parse_miniscript("and(pk(Alice),older(10))")
    assert policy.fully_parsed
    assert "Alice" in policy.keys
    assert policy.has_timelock
    assert not policy.has_hashlock
    assert policy.canonical.startswith("and(")
    assert policy.policy_digest.startswith("sha256:")


def test_threshold_multisig_policy(frontend: BitcoinScriptFrontend) -> None:
    policy = frontend.parse_miniscript("multi(2,A,B,C)")
    assert policy.thresholds == ((2, 3),)
    assert set(policy.keys) == {"A", "B", "C"}


def test_policy_equality_proven(frontend: BitcoinScriptFrontend) -> None:
    left = "and(pk(A),pk(B))"
    right = "and(pk(A),pk(B))"
    assert frontend.compare_policies(left, right) is PolicyEquivalenceStatus.PROVEN_EQUAL
    assert (
        frontend.compare_policies("pk(A)", "pk(B)")
        is PolicyEquivalenceStatus.PROVEN_UNEQUAL
    )


def test_descriptor_parse_and_mismatch(frontend: BitcoinScriptFrontend) -> None:
    desc = frontend.parse_descriptor("wsh(multi(2,A,B,C))")
    assert desc.descriptor_type.value == "wsh"
    assert desc.miniscript is not None
    assert desc.miniscript.thresholds == ((2, 3),)

    # Policy vs descriptor mismatch
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        script_pubkey=P2WSH,
        prevout=frontend.bind_prevout(
            txid=TXID, vout=0, value_sats=10_000, script_pubkey=P2WSH
        ),
        policy_expression="pk(OnlyAlice)",
        descriptor="wsh(multi(2,A,B,C))",
        claim_pass=True,
    )
    assert result.policy_equivalence is PolicyEquivalenceStatus.PROVEN_UNEQUAL
    assert result.semantic_pass_status is SemanticPassStatus.FAIL_CLOSED
    assert any("mismatch" in d for d in result.diagnostics)


def test_descriptor_checksum_recorded() -> None:
    # Checksum not validated cryptographically; presence is recorded.
    desc = parse_descriptor("pkh(xpubABC)#checksum1")
    assert desc.checksum_present
    assert desc.checksum == "checksum1"


def test_unknown_policy_equality() -> None:
    # Unknown fragment → not fully parsed → equality unknown
    left = parse_miniscript("weirdfrag(X)")
    right = parse_miniscript("weirdfrag(X)")
    assert not left.fully_parsed
    assert left.equivalence(right) is PolicyEquivalenceStatus.UNKNOWN


# ---------------------------------------------------------------------------
# PSBT bindings
# ---------------------------------------------------------------------------


def test_psbt_input_and_binding(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=25_000, script_pubkey=P2WPKH
    )
    inp = frontend.bind_psbt_input(
        input_index=0,
        prevout=prev,
        witness_items=[b"\x30" + b"\x00" * 70, b"\x02" + b"\x11" * 32],
        sighash_type=int(SighashFlag.ALL),
        sequence=0xFFFFFFFE,
        is_final=True,
    )
    assert inp.complete
    assert inp.sighash is not None
    assert not inp.sighash.is_weak

    psbt = frontend.bind_psbt([inp], locktime=0, version=2, mark_complete=True)
    assert psbt.all_prevouts_known
    assert psbt.complete
    assert not psbt.has_weak_sighash

    result = frontend.normalize_psbt_spend(
        chain_id="bitcoin-mainnet",
        psbt=psbt,
        network="mainnet",
        claim_pass=True,
    )
    assert result.psbt is not None
    assert result.psbt.complete
    assert result.semantic_pass_status is SemanticPassStatus.PASS


def test_psbt_weak_sighash_and_missing_prevout(
    frontend: BitcoinScriptFrontend,
) -> None:
    # Missing prevout → incomplete input
    weak_inp = frontend.bind_psbt_input(
        input_index=0,
        prevout=None,
        sighash_type=int(SighashFlag.NONE),
        witness_items=[b"\x01"],
    )
    assert not weak_inp.complete
    assert weak_inp.sighash is not None and weak_inp.sighash.is_weak

    psbt = frontend.bind_psbt([weak_inp], mark_complete=False)
    assert not psbt.all_prevouts_known
    assert psbt.has_weak_sighash
    assert not psbt.complete

    result = frontend.normalize_psbt_spend(
        chain_id="bitcoin-mainnet",
        psbt=psbt,
        claim_pass=True,
    )
    assert result.semantic_pass_status in {
        SemanticPassStatus.INCOMPLETE,
        SemanticPassStatus.FAIL_CLOSED,
    }


def test_psbt_complete_rejected_when_prevout_missing(
    frontend: BitcoinScriptFrontend,
) -> None:
    inp = frontend.bind_psbt_input(input_index=0, prevout=None)
    with pytest.raises(InvalidRequestError):
        frontend.bind_psbt([inp], mark_complete=True)


# ---------------------------------------------------------------------------
# Fail-closed helpers / hashlock / unsupported
# ---------------------------------------------------------------------------


def test_incomplete_spend_never_passes_helper() -> None:
    assert (
        incomplete_spend_never_passes(
            fully_decoded=False,
            unsupported_opcodes=(),
            prevout_known=True,
            weak_sighash=False,
            claim_pass=True,
        )
        is SemanticPassStatus.FAIL_CLOSED
    )
    assert (
        incomplete_spend_never_passes(
            fully_decoded=True,
            unsupported_opcodes=(0x0C,),
            prevout_known=True,
            weak_sighash=False,
            claim_pass=False,
        )
        is SemanticPassStatus.UNSUPPORTED
    )
    assert (
        incomplete_spend_never_passes(
            fully_decoded=True,
            unsupported_opcodes=(),
            prevout_known=True,
            weak_sighash=False,
            hidden_branch=True,
            claim_pass=True,
        )
        is SemanticPassStatus.INCOMPLETE
    )


def test_hashlock_extraction(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=500, script_pubkey=HASHLOCK
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=HASHLOCK,
    )
    assert result.stack is not None
    assert result.stack.hashlocks
    assert result.stack.hashlocks[0].hash_function == "sha256"
    assert not result.stack.hashlocks[0].preimage_known


def test_unsupported_opcode_blocks_pass(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=100, script_pubkey=UNSUPPORTED_SCRIPT
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=UNSUPPORTED_SCRIPT,
        claim_pass=True,
    )
    assert result.primary_program is not None
    assert result.primary_program.unsupported_opcodes
    assert result.semantic_pass_status in {
        SemanticPassStatus.UNSUPPORTED,
        SemanticPassStatus.FAIL_CLOSED,
        SemanticPassStatus.INCOMPLETE,
    }


def test_policy_only_cannot_claim_execution_pass(
    frontend: BitcoinScriptFrontend,
) -> None:
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        policy_expression="pk(Alice)",
        claim_pass=True,
    )
    assert result.analysis_mode is AnalysisMode.POLICY_ONLY
    assert result.semantic_pass_status is SemanticPassStatus.FAIL_CLOSED


def test_normalization_result_serializable(frontend: BitcoinScriptFrontend) -> None:
    prev = frontend.bind_prevout(
        txid=TXID, vout=0, value_sats=1, script_pubkey=P2PKH
    )
    result = frontend.analyze_spend(
        chain_id="bitcoin-mainnet",
        prevout=prev,
        script_pubkey=P2PKH,
        sighash_type=int(SighashFlag.ALL),
        claim_pass=True,
    )
    payload = result.to_dict()
    assert payload["chain_id"] == "bitcoin-mainnet"
    assert payload["semantic_pass_status"] == "pass"
    assert result.content_digest().startswith("sha256:")
    # Explicit non-account modeling markers
    assert "account_balance" not in payload
    assert "storage_slot" not in payload


def test_txid_normalization_rejects_bad() -> None:
    frontend = BitcoinScriptFrontend()
    with pytest.raises(InvalidRequestError):
        frontend.bind_prevout(
            txid="not-a-txid",
            vout=0,
            value_sats=1,
            script_pubkey=P2PKH,
        )


def test_witness_resource_limit(frontend: BitcoinScriptFrontend) -> None:
    tiny = BitcoinScriptFrontend(max_witness_items=1)
    with pytest.raises(ResourceLimitError):
        tiny.bind_witness([b"\x01", b"\x02"])
