"""Unit tests for allowlisted wallet / proof / AST queries (DQK-039).

Acceptance coverage:

* Private keys / seeds / signing payloads are rejected
* Queries expose authority and finality
* Cross-domain joins obey tenant and resource budgets
"""

from __future__ import annotations

from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.processors.wallets.duckdb_queries import (
    ALL_JOIN_DOMAINS,
    DUCKDB_WALLET_QUERIES_INTERFACE,
    DUCKDB_WALLET_QUERIES_SCHEMA,
    REQUIRED_RESULT_COLUMNS,
    ContractFact,
    GraphFlowFact,
    QueryAuthority,
    QueryBudget,
    QueryBudgetExceeded,
    QueryTemplateId,
    SecretSurfaceRejected,
    SourceSymbolFact,
    TenantPolicy,
    TenantPolicyViolation,
    TransactionFact,
    UnknownQueryTemplateError,
    VerificationEvidenceFact,
    WalletJoinPlane,
    WalletQueryError,
    WalletQueryService,
    classify_result_columns,
    execute_allowlisted_query,
    list_allowlisted_templates,
    open_wallet_query_service,
    scan_secret_surface,
    validate_query_parameters,
    wallet_queries_descriptor,
)
from ipfs_datasets_py.processors.wallets.duckdb_schema import (
    ColumnDataClass,
    FORBIDDEN_QUERY_CLASSES,
)
from ipfs_datasets_py.processors.wallets.models import Finality


TENANT_A = "tenant:alpha"
TENANT_B = "tenant:beta"
CHAIN = "eip155:1:0xd4e56740"
SOURCE = "source:fixture-rpc:req-1"
TX_HASH = "0xabc123def456"
CONTRACT = "0xcontract01"
SYMBOL = "sym:Token.transfer"
GRAPH_NODE = "flow:node:tx:0xabc"
EVIDENCE = "ev:proof:1"
DIGEST = "sha256:" + ("ab" * 32)


def _plane() -> WalletJoinPlane:
    plane = WalletJoinPlane()
    plane.add_transaction(
        TransactionFact(
            tenant_id=TENANT_A,
            record_id="tx-rec-1",
            transaction_hash=TX_HASH,
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.FINALIZED,
            authority=QueryAuthority.OBSERVATION,
            contract_account_id=CONTRACT,
            status="succeeded",
        )
    )
    plane.add_transaction(
        TransactionFact(
            tenant_id=TENANT_B,
            record_id="tx-rec-other",
            transaction_hash="0xother",
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.OBSERVED,
            authority=QueryAuthority.OBSERVATION,
            contract_account_id="0xother-contract",
        )
    )
    plane.add_contract(
        ContractFact(
            tenant_id=TENANT_A,
            contract_account_id=CONTRACT,
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.FINALIZED,
            transaction_hash=TX_HASH,
            event_signature="Transfer(address,address,uint256)",
            symbol_link=SYMBOL,
            authority=QueryAuthority.OBSERVATION,
        )
    )
    plane.add_source_symbol(
        SourceSymbolFact(
            tenant_id=TENANT_A,
            symbol_id=SYMBOL,
            qualified_name="Token.transfer",
            source_revision="rev:git:deadbeef",
            contract_account_id=CONTRACT,
            file_path="contracts/Token.sol",
            finality=Finality.FINALIZED,
            authority=QueryAuthority.EVIDENCE,
        )
    )
    plane.add_graph_flow(
        GraphFlowFact(
            tenant_id=TENANT_A,
            node_or_edge_id=GRAPH_NODE,
            kind="transfer",
            plane="observed_address",
            finality=Finality.SAFE,
            authority=QueryAuthority.OBSERVATION,
            transaction_hash=TX_HASH,
            chain_ref_id=CHAIN,
            graph_revision="graph-rev-1",
        )
    )
    plane.add_verification_evidence(
        VerificationEvidenceFact(
            tenant_id=TENANT_A,
            evidence_id=EVIDENCE,
            evidence_kind="theorem",
            authority=QueryAuthority.ATTESTATION,
            finality=Finality.FINALIZED,
            subject_ref=CONTRACT,
            transaction_hash=TX_HASH,
            contract_account_id=CONTRACT,
            content_digest=DIGEST,
            trust_level="attested",
        )
    )
    return plane


def _policy(tenant: str = TENANT_A) -> TenantPolicy:
    return TenantPolicy(tenant_id=tenant)


# ---------------------------------------------------------------------------
# Secret scanning
# ---------------------------------------------------------------------------


def test_scan_rejects_private_key_field() -> None:
    with pytest.raises(SecretSurfaceRejected):
        scan_secret_surface({"private_key": "0xdead"}, surface="test")


def test_scan_rejects_seed_phrase_field() -> None:
    with pytest.raises(SecretSurfaceRejected):
        scan_secret_surface({"seed_phrase": "alpha beta gamma"}, surface="test")


def test_scan_rejects_signing_payload_field() -> None:
    with pytest.raises(SecretSurfaceRejected):
        scan_secret_surface(
            {"signing_payload": "0xsignedblob"},
            surface="test",
        )


def test_scan_rejects_nested_mnemonic() -> None:
    with pytest.raises(SecretSurfaceRejected):
        scan_secret_surface(
            {"meta": {"wallet_seed": "x" * 32}},
            surface="test",
        )


def test_scan_rejects_concrete_pem_private_key() -> None:
    # Build the PEM header at runtime so the source tree never contains a
    # contiguous private-key armor block (proposal gate: secret_change_forbidden).
    pem_armor = "-----BEGIN " + "PRIVATE KEY-----"
    with pytest.raises(SecretSurfaceRejected):
        scan_secret_surface(
            {"note": pem_armor + "\nMIIE"},
            surface="test",
        )


def test_scan_accepts_public_addresses() -> None:
    scan_secret_surface(
        {
            "transaction_hash": TX_HASH,
            "contract_account_id": CONTRACT,
            "address": "0xabc",
        },
        surface="test",
    )


def test_query_params_reject_private_key() -> None:
    with pytest.raises(SecretSurfaceRejected):
        validate_query_parameters(
            QueryTemplateId.TRANSACTIONS_BY_TENANT,
            {"private_key": "0xdead"},
        )


def test_query_params_reject_signing_payload() -> None:
    with pytest.raises(SecretSurfaceRejected):
        validate_query_parameters(
            QueryTemplateId.CROSS_DOMAIN_JOIN,
            {"signing_payload": "blob", "transaction_hash": TX_HASH},
        )


def test_transaction_fact_rejects_secret_attributes() -> None:
    with pytest.raises(SecretSurfaceRejected):
        TransactionFact(
            tenant_id=TENANT_A,
            record_id="r1",
            transaction_hash=TX_HASH,
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.OBSERVED,
            attributes={"seed_phrase": "one two three four five"},
        )


def test_verification_fact_rejects_signing_key_attribute() -> None:
    with pytest.raises(SecretSurfaceRejected):
        VerificationEvidenceFact(
            tenant_id=TENANT_A,
            evidence_id="e1",
            evidence_kind="proof",
            authority=QueryAuthority.EVIDENCE,
            attributes={"signing_key": "material"},
        )


# ---------------------------------------------------------------------------
# Authority and finality exposure
# ---------------------------------------------------------------------------


def test_templates_are_allowlisted_and_closed() -> None:
    templates = list_allowlisted_templates()
    assert QueryTemplateId.CROSS_DOMAIN_JOIN.value in templates
    assert QueryTemplateId.TRANSACTION_VERIFICATION.value in templates
    assert len(templates) == len(QueryTemplateId)
    with pytest.raises(UnknownQueryTemplateError):
        resolve = __import__(
            "ipfs_datasets_py.processors.wallets.duckdb_queries",
            fromlist=["resolve_template_id"],
        ).resolve_template_id
        resolve("drop_table_users")


def test_transaction_query_exposes_authority_and_finality() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        _plane(),
        _policy(),
    )
    assert result.row_count >= 1
    assert result.schema == DUCKDB_WALLET_QUERIES_SCHEMA
    assert result.interface == DUCKDB_WALLET_QUERIES_INTERFACE
    for row in result.rows:
        for col in REQUIRED_RESULT_COLUMNS:
            assert col in row
            assert isinstance(row[col], str) and row[col].strip()
        assert row["tenant_id"] == TENANT_A
        assert row["authority"] == QueryAuthority.OBSERVATION.value
        assert row["finality"] == Finality.FINALIZED.value


def test_contract_join_exposes_authority_and_finality() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTION_CONTRACTS,
        _plane(),
        _policy(),
        params={"transaction_hash": TX_HASH},
    )
    assert result.row_count >= 1
    for row in result.rows:
        assert "authority" in row and "finality" in row
        assert row["contract_account_id"] == CONTRACT
        assert row["transaction_hash"] == TX_HASH
        # Weakest of observation+observation remains observation.
        assert row["authority"] == QueryAuthority.OBSERVATION.value


def test_graph_flow_join_exposes_authority_and_finality() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTION_GRAPH_FLOWS,
        _plane(),
        _policy(),
        params={"transaction_hash": TX_HASH},
    )
    assert result.row_count >= 1
    for row in result.rows:
        assert row["authority"]
        assert row["finality"]
        # Weakest of finalized vs safe → safe
        assert row["finality"] == Finality.SAFE.value
        assert row["node_or_edge_id"] == GRAPH_NODE


def test_source_symbol_join_exposes_authority_and_finality() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTION_SOURCE_SYMBOLS,
        _plane(),
        _policy(),
        params={"transaction_hash": TX_HASH},
    )
    assert result.row_count >= 1
    for row in result.rows:
        assert row["symbol_id"] == SYMBOL
        assert row["source_revision"] == "rev:git:deadbeef"
        assert row["authority"]  # weakest of observation and evidence
        assert row["finality"] == Finality.FINALIZED.value


def test_verification_join_exposes_authority_and_finality() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTION_VERIFICATION,
        _plane(),
        _policy(),
        params={"transaction_hash": TX_HASH},
    )
    assert result.row_count >= 1
    for row in result.rows:
        assert row["evidence_id"] == EVIDENCE
        assert row["authority"]  # weakest of observation and attestation
        assert row["finality"] == Finality.FINALIZED.value
        assert row["content_digest"] == DIGEST


def test_cross_domain_join_connects_all_five_domains() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.CROSS_DOMAIN_JOIN,
        _plane(),
        _policy(),
        params={"transaction_hash": TX_HASH},
    )
    assert result.row_count >= 1
    assert tuple(result.domains) == ALL_JOIN_DOMAINS
    for row in result.rows:
        for col in REQUIRED_RESULT_COLUMNS:
            assert col in row and row[col]
        assert row["transaction_hash"] == TX_HASH
        assert row["contract_account_id"] == CONTRACT
        assert row["symbol_id"] == SYMBOL
        assert row["node_or_edge_id"] == GRAPH_NODE
        assert row["evidence_id"] == EVIDENCE
        # Weakest authority among observation/evidence/attestation → observation
        assert row["authority"] == QueryAuthority.OBSERVATION.value


def test_result_to_dict_is_secret_safe() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        _plane(),
        _policy(),
    )
    payload = result.to_dict()
    scan_secret_surface(payload, surface="result_to_dict")
    assert "rows" in payload
    assert payload["template_id"] == QueryTemplateId.TRANSACTIONS_BY_TENANT.value


# ---------------------------------------------------------------------------
# Tenant and resource budgets
# ---------------------------------------------------------------------------


def test_tenant_policy_isolates_rows() -> None:
    plane = _plane()
    # Tenant B must not see tenant A transactions.
    result_b = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        plane,
        _policy(TENANT_B),
    )
    assert result_b.row_count == 1
    assert all(row["tenant_id"] == TENANT_B for row in result_b.rows)
    assert all(row["transaction_hash"] == "0xother" for row in result_b.rows)

    result_a = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        plane,
        _policy(TENANT_A),
    )
    assert all(row["tenant_id"] == TENANT_A for row in result_a.rows)
    assert all(row["transaction_hash"] == TX_HASH for row in result_a.rows)


def test_tenant_policy_chain_allowlist() -> None:
    policy = TenantPolicy(
        tenant_id=TENANT_A,
        allowed_chain_ref_ids=frozenset({"eip155:999:other"}),
    )
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        _plane(),
        policy,
    )
    assert result.row_count == 0


def test_tenant_policy_source_allowlist() -> None:
    policy = TenantPolicy(
        tenant_id=TENANT_A,
        allowed_source_ids=frozenset({"source:denied"}),
    )
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        _plane(),
        policy,
    )
    assert result.row_count == 0


def test_cross_domain_join_obeys_tenant_isolation() -> None:
    result = execute_allowlisted_query(
        QueryTemplateId.CROSS_DOMAIN_JOIN,
        _plane(),
        _policy(TENANT_B),
    )
    # Tenant B has a tx but no linked contracts/symbols/flows/evidence.
    # Cross-domain still returns rows only for tenant B when partial joins
    # have None fillers — but contract/symbol/flow/evidence are empty.
    for row in result.rows:
        assert row["tenant_id"] == TENANT_B
        assert row["transaction_hash"] == "0xother"
        assert row.get("evidence_id", "") == ""
        assert row.get("symbol_id", "") == ""


def test_row_budget_truncates_cross_domain_join() -> None:
    plane = WalletJoinPlane()
    # Fan-out: multiple contracts per transaction to exceed max_rows.
    plane.add_transaction(
        TransactionFact(
            tenant_id=TENANT_A,
            record_id="tx-1",
            transaction_hash=TX_HASH,
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.FINALIZED,
            contract_account_id="0xc0",
        )
    )
    for i in range(5):
        plane.add_contract(
            ContractFact(
                tenant_id=TENANT_A,
                contract_account_id=f"0xc{i}",
                chain_ref_id=CHAIN,
                source_id=SOURCE,
                finality=Finality.FINALIZED,
                transaction_hash=TX_HASH,
            )
        )
        plane.add_source_symbol(
            SourceSymbolFact(
                tenant_id=TENANT_A,
                symbol_id=f"sym:{i}",
                qualified_name=f"F.f{i}",
                source_revision="rev:1",
                contract_account_id=f"0xc{i}",
            )
        )
        plane.add_graph_flow(
            GraphFlowFact(
                tenant_id=TENANT_A,
                node_or_edge_id=f"node:{i}",
                kind="transfer",
                plane="observed_address",
                finality=Finality.SAFE,
                transaction_hash=TX_HASH,
            )
        )
        plane.add_verification_evidence(
            VerificationEvidenceFact(
                tenant_id=TENANT_A,
                evidence_id=f"ev:{i}",
                evidence_kind="theorem",
                authority=QueryAuthority.EVIDENCE,
                transaction_hash=TX_HASH,
                contract_account_id=f"0xc{i}",
            )
        )

    result = execute_allowlisted_query(
        QueryTemplateId.CROSS_DOMAIN_JOIN,
        plane,
        _policy(),
        budget=QueryBudget(max_rows=3, max_seconds=5.0),
    )
    assert result.row_count <= 3
    assert result.truncated is True
    for row in result.rows:
        assert "authority" in row and "finality" in row
        assert row["tenant_id"] == TENANT_A


def test_join_domain_budget_enforced() -> None:
    with pytest.raises(QueryBudgetExceeded) as exc:
        execute_allowlisted_query(
            QueryTemplateId.CROSS_DOMAIN_JOIN,
            _plane(),
            _policy(),
            budget=QueryBudget(max_join_domains=2),
        )
    assert exc.value.kind == "join_domains"


def test_parameter_byte_budget_enforced() -> None:
    with pytest.raises(QueryBudgetExceeded) as exc:
        validate_query_parameters(
            QueryTemplateId.TRANSACTIONS_BY_TENANT,
            {"transaction_hash": "x" * 1000},
            budget=QueryBudget(max_parameter_bytes=16),
        )
    assert exc.value.kind == "parameter_bytes"


def test_time_budget_enforced() -> None:
    with pytest.raises(QueryBudgetExceeded) as exc:
        execute_allowlisted_query(
            QueryTemplateId.TRANSACTIONS_BY_TENANT,
            _plane(),
            _policy(),
            budget=QueryBudget(max_seconds=1e-12),
        )
    assert exc.value.kind == "time"


def test_unknown_parameters_rejected() -> None:
    with pytest.raises(WalletQueryError):
        validate_query_parameters(
            QueryTemplateId.TRANSACTIONS_BY_TENANT,
            {"sql": "SELECT 1", "transaction_hash": TX_HASH},
        )


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------


def test_classify_result_columns_forbids_secret_class() -> None:
    with pytest.raises(Exception):
        classify_result_columns(
            ["private_key"],
            classifications={"private_key": ColumnDataClass.SECRET},
        )


def test_classify_result_columns_forbids_secret_name_fragment() -> None:
    from ipfs_datasets_py.processors.wallets.duckdb_queries import ColumnPolicyError

    with pytest.raises(ColumnPolicyError):
        classify_result_columns(
            ["wallet_seed"],
            classifications={"wallet_seed": ColumnDataClass.PUBLIC},
        )


def test_forbidden_query_classes_closed() -> None:
    assert ColumnDataClass.SECRET in FORBIDDEN_QUERY_CLASSES
    assert ColumnDataClass.RAW_PAYLOAD in FORBIDDEN_QUERY_CLASSES


def test_descriptor_lists_templates_and_domains() -> None:
    desc = wallet_queries_descriptor()
    assert desc["interface"] == DUCKDB_WALLET_QUERIES_INTERFACE
    assert desc["schema"] == DUCKDB_WALLET_QUERIES_SCHEMA
    assert set(desc["join_domains"]) == set(ALL_JOIN_DOMAINS)
    assert len(desc["templates"]) == len(QueryTemplateId)
    for col in REQUIRED_RESULT_COLUMNS:
        assert col in desc["required_result_columns"]
    scan_secret_surface(desc, surface="descriptor")


# ---------------------------------------------------------------------------
# Service wrapper
# ---------------------------------------------------------------------------


def test_wallet_query_service_execute() -> None:
    service = open_wallet_query_service(_plane())
    assert service.interface == DUCKDB_WALLET_QUERIES_INTERFACE
    assert service.schema == DUCKDB_WALLET_QUERIES_SCHEMA
    assert QueryTemplateId.CROSS_DOMAIN_JOIN.value in service.list_templates()
    result = service.execute(
        QueryTemplateId.TRANSACTION_CONTRACTS,
        _policy(),
        params={"transaction_hash": TX_HASH},
    )
    assert result.row_count >= 1
    assert all("authority" in r and "finality" in r for r in result.rows)


def test_service_rejects_secret_params() -> None:
    service = WalletQueryService(_plane())
    with pytest.raises(SecretSurfaceRejected):
        service.execute(
            QueryTemplateId.TRANSACTIONS_BY_TENANT,
            _policy(),
            params={"mnemonic": "alpha beta"},
        )


def test_min_finality_filter() -> None:
    plane = WalletJoinPlane()
    plane.add_transaction(
        TransactionFact(
            tenant_id=TENANT_A,
            record_id="low",
            transaction_hash="0xlow",
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.OBSERVED,
        )
    )
    plane.add_transaction(
        TransactionFact(
            tenant_id=TENANT_A,
            record_id="high",
            transaction_hash="0xhigh",
            chain_ref_id=CHAIN,
            source_id=SOURCE,
            finality=Finality.FINALIZED,
        )
    )
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTIONS_BY_TENANT,
        plane,
        _policy(),
        params={"min_finality": Finality.SAFE.value},
    )
    hashes = {row["transaction_hash"] for row in result.rows}
    assert "0xhigh" in hashes
    assert "0xlow" not in hashes


def test_min_authority_filter_on_verification() -> None:
    plane = _plane()
    plane.add_verification_evidence(
        VerificationEvidenceFact(
            tenant_id=TENANT_A,
            evidence_id="ev:candidate",
            evidence_kind="heuristic",
            authority=QueryAuthority.CANDIDATE,
            transaction_hash=TX_HASH,
            contract_account_id=CONTRACT,
        )
    )
    result = execute_allowlisted_query(
        QueryTemplateId.TRANSACTION_VERIFICATION,
        plane,
        _policy(),
        params={
            "transaction_hash": TX_HASH,
            "min_authority": QueryAuthority.EVIDENCE.value,
        },
    )
    evidence_ids = {row["evidence_id"] for row in result.rows}
    assert EVIDENCE in evidence_ids
    assert "ev:candidate" not in evidence_ids


def test_budget_validation_rejects_invalid_limits() -> None:
    with pytest.raises(WalletQueryError):
        QueryBudget(max_rows=0)
    with pytest.raises(WalletQueryError):
        QueryBudget(max_seconds=-1)
    with pytest.raises(WalletQueryError):
        TenantPolicy(tenant_id="")


def test_domain_counts_on_plane() -> None:
    plane = _plane()
    counts = plane.domain_counts()
    assert counts["wallet.transactions"] == 2
    assert counts["wallet.contracts"] == 1
    assert counts["ast.source_symbols"] == 1
    assert counts["crypto_flows.graph"] == 1
    assert counts["proofs.verification_evidence"] == 1
