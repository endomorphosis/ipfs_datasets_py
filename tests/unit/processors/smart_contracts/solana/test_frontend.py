"""CRYPTOIR-G230 Solana program frontend and deployment semantics.

Acceptance coverage:

* Loader version, executable/program-data relation, binary hash, deployment
  slot, upgrade authority, IDL/build correspondence are explicit;
* signer/writable privileges, PDA seeds, owners are first-class semantics
  (not generic call metadata);
* CPI graph, inner instructions, and coverage are explicit;
* source claims without reproducible SBF equality remain evidence only;
* offline program fixtures with loader, CPI, upgrade, and account-substitution
  paths.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.smart_contracts.artifacts import bytes_digest
from ipfs_datasets_py.processors.smart_contracts.errors import (
    InvalidRequestError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.smart_contracts.models import (
    AcquisitionStatus,
    ArtifactKind,
    ChainRef,
    ContractAcquisitionRequest,
    ProviderPolicy,
)
from ipfs_datasets_py.processors.smart_contracts.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.smart_contracts.solana import (
    BPF_LOADER_UPGRADEABLE,
    BPF_LOADER_V2,
    AnalysisMode,
    AccountPrivilege,
    CPIEdge,
    CPIEdgeKind,
    CPIGraph,
    LoaderVersion,
    OfflineSolanaProvider,
    OwnerCheckStatus,
    PDAConstraint,
    ProgramAccountKind,
    ProgramDataEpoch,
    SemanticPassStatus,
    SolanaProgramFixture,
    SolanaProgramFrontend,
    SourceEquivalenceStatus,
    UpgradeAuthority,
    UpgradeAuthorityState,
    bind_pda_constraint,
    bind_program_relation,
    bind_upgrade_authority,
    build_cpi_graph,
    check_account_owner,
    incomplete_coverage_never_passes,
    normalize_elf_bytes,
    normalize_pubkey,
)


NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)

# Deterministic 32-byte base58 pubkeys (from fixed byte patterns).
PROGRAM_ID = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"  # bytes([1]*32)
AUTHORITY = "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR"  # bytes([2]*32)
PROGRAM_DATA = "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8"  # bytes([3]*32)
PDA_ADDR = "GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq"  # bytes([4]*32)
ACCOUNT_A = "LbUiWL3xVV8hTFYBVdbTNrpDo41NKS6o3LHHuDzjfcY"  # bytes([5]*32)

# Minimal ELF: magic + padding (not a real SBF image, but valid header).
MINIMAL_ELF = b"\x7fELF" + b"\x00" * 60
ALT_ELF = b"\x7fELF" + b"\x01" * 60


@pytest.fixture
def frontend() -> SolanaProgramFrontend:
    return SolanaProgramFrontend()


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="solana-g230",
        limits=RequestLimits(
            max_items=8,
            max_requests=16,
            max_response_bytes=1024 * 1024,
            max_depth=4,
        ),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# AST symbols / public surface
# ---------------------------------------------------------------------------


def test_ast_symbols_are_exportable() -> None:
    """AST query: SolanaProgramFrontend ProgramDataEpoch UpgradeAuthority CPIEdge PDAConstraint."""

    assert SolanaProgramFrontend is not None
    assert ProgramDataEpoch is not None
    assert UpgradeAuthority is not None
    assert CPIEdge is not None
    assert PDAConstraint is not None


def test_pubkey_normalization_round_trip() -> None:
    assert normalize_pubkey(PROGRAM_ID) == PROGRAM_ID
    with pytest.raises(InvalidRequestError):
        normalize_pubkey("not-a-key")


# ---------------------------------------------------------------------------
# Loader / program-data epoch binding
# ---------------------------------------------------------------------------


def test_program_epoch_binds_required_fields(frontend: SolanaProgramFrontend) -> None:
    epoch = frontend.bind_program_epoch(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        loader_program_id=BPF_LOADER_UPGRADEABLE,
        deployment_slot=250_000_000,
        code_epoch="epoch-1",
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        idl=b'{"name":"demo","instructions":[]}',
        build_manifest=b'{"solana-program":"1.18"}',
        compiler="anchor",
        compiler_version="0.29.0",
        compiler_flags={"features": ["cpi"]},
        network="solana-mainnet-beta",
        genesis_hash="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    )
    payload = epoch.to_dict()
    assert payload["chain_id"] == "mainnet-beta"
    assert payload["program_id"] == PROGRAM_ID
    assert payload["deployment_slot"] == 250_000_000
    assert payload["code_epoch"] == "epoch-1"
    assert payload["loader_version"] == LoaderVersion.BPF_UPGRADEABLE.value
    assert payload["loader_program_id"] == BPF_LOADER_UPGRADEABLE
    assert payload["program_data_address"] == PROGRAM_DATA
    assert payload["binary_digest"] == bytes_digest(MINIMAL_ELF)
    assert payload["idl_digest"].startswith("sha256:")
    assert payload["build_manifest_digest"].startswith("sha256:")
    assert payload["compiler"] == "anchor"
    assert payload["compiler_version"] == "0.29.0"
    assert payload["upgrade_authority"]["state"] == UpgradeAuthorityState.AUTHORITY_SET.value
    assert payload["upgrade_authority"]["authority_pubkey"] == AUTHORITY
    assert epoch.content_digest().startswith("sha256:")


def test_program_epoch_from_fixture() -> None:
    fixture = SolanaProgramFixture(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        loader_program_id=BPF_LOADER_UPGRADEABLE,
        program_data_address=PROGRAM_DATA,
        upgrade_authority=AUTHORITY,
        deployment_slot=100,
        code_epoch="fixture-epoch",
        compiler="cargo-build-sbf",
        compiler_version="1.18.0",
        idl_json=b'{"version":"0.1.0"}',
    )
    epoch = ProgramDataEpoch.from_fixture(fixture, network="solana-mainnet-beta")
    assert epoch.deployment_slot == 100
    assert epoch.compiler == "cargo-build-sbf"
    assert epoch.program_data_address == PROGRAM_DATA
    assert epoch.upgrade_authority is not None
    assert epoch.upgrade_authority.is_upgradeable is True


def test_executable_program_data_relation() -> None:
    relation = bind_program_relation(
        program_id=PROGRAM_ID,
        loader_program_id=BPF_LOADER_UPGRADEABLE,
        program_data_address=PROGRAM_DATA,
        sbf_elf=MINIMAL_ELF,
        deployment_slot=42,
    )
    assert relation.account_kind is ProgramAccountKind.EXECUTABLE_PROGRAM
    assert relation.loader_version is LoaderVersion.BPF_UPGRADEABLE
    assert relation.program_data_address == PROGRAM_DATA
    assert relation.binary_digest == bytes_digest(MINIMAL_ELF)
    assert relation.deployment_slot == 42
    assert relation.executable is True
    assert relation.owner_program_id == BPF_LOADER_UPGRADEABLE


def test_upgradeable_requires_program_data_address() -> None:
    with pytest.raises(InvalidRequestError, match="program_data_address"):
        bind_program_relation(
            program_id=PROGRAM_ID,
            loader_program_id=BPF_LOADER_UPGRADEABLE,
            sbf_elf=MINIMAL_ELF,
        )


def test_non_upgradeable_loader_v2() -> None:
    relation = bind_program_relation(
        program_id=PROGRAM_ID,
        loader_program_id=BPF_LOADER_V2,
        sbf_elf=MINIMAL_ELF,
        deployment_slot=1,
    )
    assert relation.loader_version is LoaderVersion.BPF_V2
    assert relation.program_data_address == ""
    authority = bind_upgrade_authority(
        authority_pubkey=AUTHORITY,
        loader_version=LoaderVersion.BPF_V2,
    )
    assert authority.state is UpgradeAuthorityState.NOT_APPLICABLE


def test_upgrade_authority_immutable() -> None:
    authority = bind_upgrade_authority(
        authority_pubkey="",
        program_data_address=PROGRAM_DATA,
        slot_observed=9,
        loader_version=LoaderVersion.BPF_UPGRADEABLE,
    )
    assert authority.state is UpgradeAuthorityState.IMMUTABLE
    assert authority.authority_pubkey == ""
    assert authority.is_upgradeable is False


def test_upgrade_authority_unknown_requires_diagnostics() -> None:
    authority = bind_upgrade_authority(
        authority_pubkey=None,
        program_data_address=PROGRAM_DATA,
        loader_version=LoaderVersion.BPF_UPGRADEABLE,
    )
    assert authority.state is UpgradeAuthorityState.UNKNOWN
    assert authority.diagnostics
    with pytest.raises(InvalidRequestError):
        UpgradeAuthority(
            state=UpgradeAuthorityState.UNKNOWN,
            diagnostics=(),
        )


# ---------------------------------------------------------------------------
# Privileges, owners, PDA (first-class, not call metadata)
# ---------------------------------------------------------------------------


def test_account_privilege_is_first_class() -> None:
    priv = AccountPrivilege(
        account_index=0,
        pubkey=ACCOUNT_A,
        is_signer=True,
        is_writable=True,
        owner=PROGRAM_ID,
    )
    payload = priv.to_dict()
    # Privilege bits and owner live at top level — not nested metadata.
    assert payload["is_signer"] is True
    assert payload["is_writable"] is True
    assert payload["owner"] == PROGRAM_ID
    assert "call_metadata" not in payload
    restored = AccountPrivilege.from_dict(payload)
    assert restored.is_signer is True
    assert restored.owner == PROGRAM_ID


def test_owner_check_match_and_mismatch() -> None:
    matched = check_account_owner(
        account_pubkey=ACCOUNT_A,
        expected_owner=PROGRAM_ID,
        observed_owner=PROGRAM_ID,
    )
    assert matched.status is OwnerCheckStatus.MATCHED

    mismatched = check_account_owner(
        account_pubkey=ACCOUNT_A,
        expected_owner=PROGRAM_ID,
        observed_owner=AUTHORITY,
    )
    assert mismatched.status is OwnerCheckStatus.MISMATCH
    assert mismatched.diagnostics

    unknown = check_account_owner(
        account_pubkey=ACCOUNT_A,
        expected_owner=PROGRAM_ID,
        observed_owner=None,
    )
    assert unknown.status is OwnerCheckStatus.UNKNOWN


def test_pda_constraint_seeds_and_bump() -> None:
    pda = bind_pda_constraint(
        program_id=PROGRAM_ID,
        seeds=(b"vault", ACCOUNT_A.encode("utf-8")[:32]),
        derived_address=PDA_ADDR,
        bump=254,
        verified=True,
        is_on_curve=False,
    )
    assert pda.verified is True
    assert pda.bump == 254
    assert pda.derived_address == PDA_ADDR
    assert pda.seeds_digest.startswith("sha256:")
    assert len(pda.seeds) == 2
    # Oversize seed fails closed.
    with pytest.raises(InvalidRequestError, match="32"):
        bind_pda_constraint(
            program_id=PROGRAM_ID,
            seeds=(b"x" * 33,),
        )


def test_cpi_edge_carries_privileges_and_owners() -> None:
    privs = (
        AccountPrivilege(
            account_index=0,
            pubkey=ACCOUNT_A,
            is_signer=True,
            is_writable=False,
            owner=PROGRAM_ID,
        ),
        AccountPrivilege(
            account_index=1,
            pubkey=AUTHORITY,
            is_signer=False,
            is_writable=True,
            owner=PROGRAM_ID,
        ),
    )
    owner_check = check_account_owner(
        account_pubkey=ACCOUNT_A,
        expected_owner=PROGRAM_ID,
        observed_owner=PROGRAM_ID,
    )
    edge = CPIEdge(
        caller_program_id=PROGRAM_ID,
        callee_program_id=BPF_LOADER_V2,
        kind=CPIEdgeKind.INVOKE_SIGNED,
        outer_index=0,
        inner_index=0,
        stack_height=2,
        account_indexes=(0, 1),
        account_privileges=privs,
        data_digest=bytes_digest(b"ix-data"),
        owner_checks=(owner_check,),
    )
    payload = edge.to_dict()
    # Privileges and owner checks are sibling first-class fields.
    assert "account_privileges" in payload
    assert "owner_checks" in payload
    assert payload["account_privileges"][0]["is_signer"] is True
    assert payload["owner_checks"][0]["status"] == "matched"
    assert edge.is_inner is True


# ---------------------------------------------------------------------------
# CPI graph / coverage / fail-closed
# ---------------------------------------------------------------------------


def test_cpi_graph_incomplete_never_passes() -> None:
    graph = build_cpi_graph(
        program_id=PROGRAM_ID,
        edges=(),
        privileges=(),
        inner_instruction_coverage=False,
        claim_pass=True,
    )
    assert graph.pass_status is SemanticPassStatus.INCOMPLETE
    assert graph.is_pass is False
    status = incomplete_coverage_never_passes(graph=graph, claim_pass=True)
    assert status is SemanticPassStatus.INCOMPLETE


def test_cpi_graph_pass_with_full_coverage() -> None:
    priv = AccountPrivilege(
        account_index=0,
        pubkey=ACCOUNT_A,
        is_signer=True,
        is_writable=True,
        owner=PROGRAM_ID,
    )
    edge = CPIEdge(
        caller_program_id=PROGRAM_ID,
        callee_program_id=BPF_LOADER_V2,
        kind=CPIEdgeKind.INVOKE,
        account_privileges=(priv,),
        account_indexes=(0,),
    )
    check = check_account_owner(
        account_pubkey=ACCOUNT_A,
        expected_owner=PROGRAM_ID,
        observed_owner=PROGRAM_ID,
    )
    graph = build_cpi_graph(
        program_id=PROGRAM_ID,
        edges=(edge,),
        privileges=(priv,),
        owner_checks=(check,),
        inner_instruction_coverage=True,
        claim_pass=True,
    )
    assert graph.pass_status is SemanticPassStatus.PASS
    assert graph.is_pass is True
    assert any("signers" in note for note in graph.coverage_notes)


def test_cpi_graph_rejects_pass_without_inner_coverage() -> None:
    with pytest.raises(InvalidRequestError, match="inner instruction"):
        CPIGraph(
            program_id=PROGRAM_ID,
            edges=(),
            inner_instruction_coverage=False,
            pass_status=SemanticPassStatus.PASS,
        )


def test_elf_size_bound(frontend: SolanaProgramFrontend) -> None:
    tiny = SolanaProgramFrontend(max_elf_bytes=8)
    with pytest.raises(ResourceLimitError):
        tiny.bind_program_epoch(
            chain_id="mainnet-beta",
            program_id=PROGRAM_ID,
            sbf_elf=MINIMAL_ELF,
            program_data_address=PROGRAM_DATA,
        )


def test_invalid_elf_magic_rejected(frontend: SolanaProgramFrontend) -> None:
    with pytest.raises(InvalidRequestError, match="ELF magic"):
        frontend.bind_program_epoch(
            chain_id="mainnet-beta",
            program_id=PROGRAM_ID,
            sbf_elf=b"not-elf-bytes-here!!!!",
            program_data_address=PROGRAM_DATA,
        )


# ---------------------------------------------------------------------------
# Source / SBF equivalence
# ---------------------------------------------------------------------------


def test_sbf_equivalence_reproduced(frontend: SolanaProgramFrontend) -> None:
    source = b"use anchor_lang::prelude::*;\n#[program]\npub mod demo {}\n"
    manifest = frontend.build_source_manifest(
        request_id="src-1",
        sources={"programs/demo/src/lib.rs": source},
        compiler="anchor",
        compiler_version="0.29.0",
        settings={"features": []},
        sbf_elf=MINIMAL_ELF,
        idl=b'{"name":"demo"}',
        code_epoch="epoch-src",
        observed_at=NOW,
    )
    status = frontend.reproduce_sbf_equivalence(manifest, sbf_elf=MINIMAL_ELF)
    assert status is SourceEquivalenceStatus.REPRODUCED


def test_sbf_equivalence_mismatch_triggers_independent_runtime(
    frontend: SolanaProgramFrontend,
) -> None:
    source = b"pub mod other {}\n"
    manifest = frontend.build_source_manifest(
        request_id="src-2",
        sources={"lib.rs": source},
        compiler="anchor",
        compiler_version="0.29.0",
        sbf_elf=MINIMAL_ELF,  # declared expected
        observed_at=NOW,
    )
    result = frontend.normalize_program(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=ALT_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        source_manifest=manifest,
        claim_semantic_pass=False,
    )
    assert result.source_equivalence is SourceEquivalenceStatus.INDEPENDENT_RUNTIME
    assert result.analysis_mode is AnalysisMode.RUNTIME_ONLY
    assert any("independently" in d for d in result.diagnostics)
    assert result.program_epoch.binary_digest == bytes_digest(ALT_ELF)


def test_source_not_declared_is_evidence_only(frontend: SolanaProgramFrontend) -> None:
    source = b"pub mod c {}\n"
    manifest = frontend.build_source_manifest(
        request_id="src-3",
        sources={"c.rs": source},
        compiler="anchor",
        compiler_version="0.28.0",
        # no SBF digests
        observed_at=NOW,
    )
    result = frontend.normalize_program(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey="",
        source_manifest=manifest,
    )
    assert result.source_equivalence is SourceEquivalenceStatus.EVIDENCE_ONLY
    assert result.analysis_mode is AnalysisMode.SOURCE_EVIDENCE_ONLY
    assert result.upgrade_authority.state is UpgradeAuthorityState.IMMUTABLE


def test_no_source_analyzes_sbf_independently(frontend: SolanaProgramFrontend) -> None:
    result = frontend.normalize_program(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        deployment_slot=1,
        upgrade_authority_pubkey=AUTHORITY,
        compiler="anchor",
        compiler_version="0.29.0",
    )
    assert result.analysis_mode is AnalysisMode.RUNTIME_ONLY
    assert result.source_equivalence is SourceEquivalenceStatus.INDEPENDENT_RUNTIME


# ---------------------------------------------------------------------------
# Full normalize + golden fixtures
# ---------------------------------------------------------------------------


def test_normalize_program_full_binding(frontend: SolanaProgramFrontend) -> None:
    priv = AccountPrivilege(
        account_index=0,
        pubkey=ACCOUNT_A,
        is_signer=True,
        is_writable=True,
        owner=PROGRAM_ID,
    )
    edge = CPIEdge(
        caller_program_id=PROGRAM_ID,
        callee_program_id=BPF_LOADER_V2,
        kind=CPIEdgeKind.INVOKE,
        account_indexes=(0,),
        account_privileges=(priv,),
        data_digest=bytes_digest(b"data"),
    )
    pda = bind_pda_constraint(
        program_id=PROGRAM_ID,
        seeds=(b"state",),
        derived_address=PDA_ADDR,
        bump=255,
        verified=True,
    )
    owner = check_account_owner(
        account_pubkey=ACCOUNT_A,
        expected_owner=PROGRAM_ID,
        observed_owner=PROGRAM_ID,
    )
    result = frontend.normalize_program(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        loader_program_id=BPF_LOADER_UPGRADEABLE,
        deployment_slot=42,
        code_epoch="golden-1",
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        idl=b'{"name":"golden"}',
        build_manifest=b'{"profile":"release"}',
        compiler="anchor",
        compiler_version="0.29.0",
        compiler_flags={"opt": 3},
        network="solana-mainnet-beta",
        edges=(edge,),
        privileges=(priv,),
        pda_constraints=(pda,),
        owner_checks=(owner,),
        inner_instruction_coverage=True,
        claim_semantic_pass=True,
    )
    assert result.program_epoch.chain_id == "mainnet-beta"
    assert result.program_epoch.deployment_slot == 42
    assert result.program_epoch.compiler == "anchor"
    assert result.program_relation.program_data_address == PROGRAM_DATA
    assert result.upgrade_authority.authority_pubkey == AUTHORITY
    assert result.is_pass is True
    assert result.cpi_graph.pda_constraints[0].bump == 255
    assert result.cpi_graph.privileges[0].is_signer is True
    assert result.content_digest().startswith("sha256:")
    payload = result.to_dict()
    assert "program_epoch" in payload
    assert "cpi_graph" in payload
    assert "upgrade_authority" in payload
    assert "private_key" not in str(payload)


def test_normalize_with_incomplete_cpi_never_passes(
    frontend: SolanaProgramFrontend,
) -> None:
    result = frontend.normalize_program(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        claim_semantic_pass=True,
        inner_instruction_coverage=False,
    )
    assert result.semantic_pass_status is SemanticPassStatus.INCOMPLETE
    assert result.is_pass is False


def test_normalize_fixture_golden_path(frontend: SolanaProgramFrontend) -> None:
    fixture = SolanaProgramFixture(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        idl_json=b'[{"name":"initialize"}]',
        source_files={"lib.rs": b"pub mod demo {}"},
        build_manifest_json=b'{"solana":"1.18"}',
        loader_program_id=BPF_LOADER_UPGRADEABLE,
        program_data_address=PROGRAM_DATA,
        upgrade_authority=AUTHORITY,
        deployment_slot=7,
        code_epoch="fixture-golden",
        compiler="anchor",
        compiler_version="0.29.0",
        compiler_flags={"features": ["no-entrypoint"]},
        account_owners={ACCOUNT_A: PROGRAM_ID},
    )
    priv = AccountPrivilege(
        account_index=0,
        pubkey=ACCOUNT_A,
        is_signer=False,
        is_writable=True,
        owner=PROGRAM_ID,
    )
    result = frontend.normalize_fixture(
        fixture,
        privileges=(priv,),
        edges=(
            CPIEdge(
                caller_program_id=PROGRAM_ID,
                callee_program_id=PROGRAM_ID,
                kind=CPIEdgeKind.OUTER,
                account_privileges=(priv,),
                account_indexes=(0,),
            ),
        ),
        owner_checks=(
            check_account_owner(
                account_pubkey=ACCOUNT_A,
                expected_owner=PROGRAM_ID,
                observed_owner=PROGRAM_ID,
            ),
        ),
        inner_instruction_coverage=True,
        claim_semantic_pass=True,
    )
    assert result.program_epoch.code_epoch == "fixture-golden"
    assert result.program_epoch.deployment_slot == 7
    assert result.is_pass is True
    # Owner checks from fixture path are first-class.
    assert result.cpi_graph.owner_checks
    assert result.cpi_graph.owner_checks[0].status is OwnerCheckStatus.MATCHED


def test_account_substitution_fixture_changes_privileges(
    frontend: SolanaProgramFrontend,
) -> None:
    """Account-substitution: rewritten privilege/owner list is semantic."""

    base_priv = AccountPrivilege(
        account_index=0,
        pubkey=ACCOUNT_A,
        is_signer=True,
        is_writable=True,
        owner=PROGRAM_ID,
    )
    substituted = AccountPrivilege(
        account_index=0,
        pubkey=AUTHORITY,  # substituted account
        is_signer=False,  # privilege change
        is_writable=True,
        owner=BPF_LOADER_V2,  # owner change
    )
    result_base = frontend.normalize_program(
        chain_id="devnet",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        privileges=(base_priv,),
        edges=(
            CPIEdge(
                caller_program_id=PROGRAM_ID,
                callee_program_id=PROGRAM_ID,
                kind=CPIEdgeKind.OUTER,
                account_privileges=(base_priv,),
            ),
        ),
        owner_checks=(
            check_account_owner(
                account_pubkey=ACCOUNT_A,
                expected_owner=PROGRAM_ID,
                observed_owner=PROGRAM_ID,
            ),
        ),
        inner_instruction_coverage=True,
        claim_semantic_pass=True,
    )
    result_sub = frontend.normalize_program(
        chain_id="devnet",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        privileges=(substituted,),
        edges=(
            CPIEdge(
                caller_program_id=PROGRAM_ID,
                callee_program_id=PROGRAM_ID,
                kind=CPIEdgeKind.OUTER,
                account_privileges=(substituted,),
            ),
        ),
        owner_checks=(
            check_account_owner(
                account_pubkey=AUTHORITY,
                expected_owner=PROGRAM_ID,
                observed_owner=BPF_LOADER_V2,
            ),
        ),
        inner_instruction_coverage=True,
        claim_semantic_pass=True,
    )
    # Digests differ because privileges/owners are semantic identity.
    assert result_base.content_digest() != result_sub.content_digest()
    assert result_sub.cpi_graph.privileges[0].is_signer is False
    assert result_sub.cpi_graph.owner_checks[0].status is OwnerCheckStatus.MISMATCH
    # Mismatch causes fail-closed even with coverage.
    assert result_sub.semantic_pass_status is SemanticPassStatus.FAIL_CLOSED


# ---------------------------------------------------------------------------
# Offline provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offline_provider_acquires_program(context: OperationContext) -> None:
    fixture = SolanaProgramFixture(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        idl_json=b"{}",
        loader_program_id=BPF_LOADER_UPGRADEABLE,
        program_data_address=PROGRAM_DATA,
        upgrade_authority=AUTHORITY,
        deployment_slot=9,
        code_epoch="prov-1",
        compiler="anchor",
        compiler_version="0.29.0",
    )
    provider = OfflineSolanaProvider([fixture])
    request = ContractAcquisitionRequest(
        request_id="acq-1",
        chain=ChainRef(
            chain="solana", network="solana-mainnet-beta", chain_id="mainnet-beta"
        ),
        artifact_kind=ArtifactKind.PROGRAM,
        locator=f"solana://mainnet-beta/{PROGRAM_ID}",
        provider_policy=ProviderPolicy(
            allowed_providers=frozenset({provider.provider_id}),
        ),
        code_epoch="prov-1",
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.AVAILABLE
    assert result.artifacts
    assert result.artifacts[0].content_digest == bytes_digest(MINIMAL_ELF)
    assert result.attributes["compiler"] == "anchor"
    assert result.attributes["code_epoch"] == "prov-1"
    assert result.attributes["loader_version"] == LoaderVersion.BPF_UPGRADEABLE.value
    assert result.attributes["upgrade_authority_state"] == "authority_set"


@pytest.mark.asyncio
async def test_offline_provider_unavailable(context: OperationContext) -> None:
    provider = OfflineSolanaProvider([])
    request = ContractAcquisitionRequest(
        request_id="acq-2",
        chain=ChainRef(
            chain="solana", network="solana-mainnet-beta", chain_id="mainnet-beta"
        ),
        artifact_kind=ArtifactKind.PROGRAM,
        locator=f"solana://mainnet-beta/{PROGRAM_ID}",
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_offline_provider_idl_and_source(context: OperationContext) -> None:
    fixture = SolanaProgramFixture(
        chain_id="mainnet-beta",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        idl_json=b'{"name":"x"}',
        source_files={
            "src/lib.rs": b"pub mod x {}",
            "src/state.rs": b"pub struct S;",
        },
        program_data_address=PROGRAM_DATA,
        upgrade_authority=AUTHORITY,
    )
    provider = OfflineSolanaProvider([fixture])
    idl_req = ContractAcquisitionRequest(
        request_id="acq-3",
        chain=ChainRef(
            chain="solana", network="solana-mainnet-beta", chain_id="mainnet-beta"
        ),
        artifact_kind=ArtifactKind.IDL,
        locator=f"solana://mainnet-beta/{PROGRAM_ID}@9",
    )
    # slot-specific key may miss; falls back to program-only
    result = await provider.acquire(idl_req, context=context)
    assert result.status is AcquisitionStatus.AVAILABLE

    source_req = ContractAcquisitionRequest(
        request_id="acq-4",
        chain=ChainRef(
            chain="solana", network="solana-mainnet-beta", chain_id="mainnet-beta"
        ),
        artifact_kind=ArtifactKind.SOURCE,
        locator=PROGRAM_ID,  # bare program id
    )
    source_result = await provider.acquire(source_req, context=context)
    assert source_result.status is AcquisitionStatus.AVAILABLE
    assert len(source_result.artifacts) == 2


@pytest.mark.asyncio
async def test_offline_provider_state_snapshot(context: OperationContext) -> None:
    fixture = SolanaProgramFixture(
        chain_id="devnet",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority="",  # immutable
        deployment_slot=3,
        account_owners={ACCOUNT_A: PROGRAM_ID},
    )
    provider = OfflineSolanaProvider([fixture])
    request = ContractAcquisitionRequest(
        request_id="acq-5",
        chain=ChainRef(chain="solana", network="solana-devnet", chain_id="devnet"),
        artifact_kind=ArtifactKind.STATE_SNAPSHOT,
        locator=f"solana://devnet/{PROGRAM_ID}",
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.AVAILABLE
    assert result.attributes["upgrade_authority_state"] == "immutable"


# ---------------------------------------------------------------------------
# Malformed / fail-closed inputs
# ---------------------------------------------------------------------------


def test_invalid_program_id_rejected(frontend: SolanaProgramFrontend) -> None:
    with pytest.raises(InvalidRequestError):
        frontend.bind_program_epoch(
            chain_id="mainnet-beta",
            program_id="0x1234",
            sbf_elf=MINIMAL_ELF,
            program_data_address=PROGRAM_DATA,
        )


def test_invalid_hex_elf_rejected() -> None:
    with pytest.raises(InvalidRequestError):
        normalize_elf_bytes("0xzz")


def test_package_exports_round_trip_dict(frontend: SolanaProgramFrontend) -> None:
    result = frontend.normalize_program(
        chain_id="devnet",
        program_id=PROGRAM_ID,
        sbf_elf=MINIMAL_ELF,
        program_data_address=PROGRAM_DATA,
        upgrade_authority_pubkey=AUTHORITY,
        network="solana-devnet",
        claim_semantic_pass=False,
    )
    payload = result.to_dict()
    assert payload["program_epoch"]["chain_id"] == "devnet"
    assert "cpi_graph" in payload
    assert "upgrade_authority" in payload
    assert "program_relation" in payload
    assert "private_key" not in str(payload)
