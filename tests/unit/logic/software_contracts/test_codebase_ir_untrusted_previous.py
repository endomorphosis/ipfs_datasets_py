"""A caller's content-addressed prior state is not extraction authority."""

from dataclasses import replace

from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    RepositoryCodebaseIndex,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    PythonSemanticAnalyzer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import (
    ProofHostResources,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceSchedulerConfig,
)


def test_untrusted_previous_semantics_are_rederived_from_captured_source(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "unit.py").write_text("def actual(n):\n    return n + 1\n")
    scheduler = GlobalResourceScheduler(
        ResourceSchedulerConfig.for_proof_host(
            state_path=tmp_path / "resources.json",
            proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
            lane_reservations={},
            auto_renew_leases=False,
        )
    )
    index = RepositoryCodebaseIndex()
    first = index.prepare(
        repository, repository_id="fixture-repository", scheduler=scheduler
    )
    source_cid = first.snapshot.entries[0].source_cid

    # This is a valid, internally self-consistent normalized AST and version
    # identity for DIFFERENT bytes. Source CID is merely rebound: it is not
    # part of the semantic SymbolRecord's recomputed version CID.
    alternate = PythonSemanticAnalyzer(
        repository_id=first.snapshot.repository_id
    ).analyze(b"def phantom(n):\n    return n - 999\n", "unit.py")
    forged_symbols = tuple(
        replace(fact.symbol, source_cid=source_cid) for fact in alternate.symbols
    )
    forged_state = replace(
        first.semantic_state,
        symbols=forged_symbols,
        edges=tuple(edge for fact in alternate.symbols for edge in fact.edges),
    )
    forged = replace(first, semantic_state=forged_state)
    assert forged.cid != first.cid
    assert any(
        symbol.qualified_name.endswith("phantom")
        for symbol in forged.semantic_state.symbols
    )
    assert all(
        symbol.source_cid == source_cid for symbol in forged.semantic_state.symbols
    )

    repaired = index.prepare(
        repository,
        repository_id="fixture-repository",
        scheduler=scheduler,
        previous=forged,
    )
    assert repaired.cid == first.cid
    assert repaired.semantic_state == first.semantic_state
    assert not any(
        symbol.qualified_name.endswith("phantom")
        for symbol in repaired.semantic_state.symbols
    )
    assert index.lookup(repaired, "unit.py").symbols[0].name == "actual"
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_native_fatal_diagnostic_with_residual_symbols_counts_as_failed(tmp_path):
    from ipfs_datasets_py.logic.software_contracts.ast_ir import DiagnosticRecord
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
        classify_parse_status,
    )
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import (
        DuckDBASTIngestor,
    )
    from ipfs_datasets_py.logic.software_contracts.python_frontend import (
        PythonASTExtractor,
    )
    from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
        snapshot_repository,
    )

    class InterruptedFrontend(PythonASTExtractor):
        def extract_from_source(self, *args, **kwargs):
            record = super().extract_from_source(*args, **kwargs)
            assert record.symbols
            return replace(
                record,
                diagnostics=(
                    DiagnosticRecord(
                        code="frontend.interrupted",
                        severity="fatal",
                        message="analysis stopped with residual symbols",
                    ),
                ),
            )

    (tmp_path / "unit.py").write_text("def actual(n):\n    return n + 1\n")
    snapshot = snapshot_repository(tmp_path, repository_id="fixture-repository")
    ingestor = DuckDBASTIngestor(frontends={"python": InterruptedFrontend()})
    published = ingestor.ingest_snapshot(snapshot)
    assert published.stats.parse_failed_count == 1
    assert published.stats.parsed_count == 0
    assert published.decisions[0].action == "parse_failed"
    projection = published.projections[0]
    assert projection.symbols
    assert projection.ast_blob.parse_status == "failed"
    assert projection.diagnostics[0].is_parse_failure
    from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord

    assert (
        classify_parse_status(ASTRecord.from_json(projection.ast_blob.payload_json))
        == "failed"
    )
