"""Unit tests for bounded proof query templates (DQK-030).

Acceptance coverage:

* Queries cannot promote an untrusted cache hit
* Freshness / applicability / revocation are always visible
* Recursive premise traversal is bounded
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
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

from ipfs_datasets_py.logic.backends.cache_protocol import (
    CachePolarity,
    content_digest,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
)
from ipfs_datasets_py.logic.common.duckdb_proof_queries import (
    AUTHORITY_COLUMNS,
    APPLICABILITY_COLUMNS,
    COMMON_PROJECTION_COLUMNS,
    DUCKDB_PROOF_QUERIES_INTERFACE,
    DUCKDB_PROOF_QUERIES_SCHEMA_VERSION,
    FRESHNESS_COLUMNS,
    PROOF_QUERY_TEMPLATES,
    ProofQueryBudget,
    ProofQueryBudgetExceeded,
    ProofQueryCatalog,
    ProofQueryError,
    ProofQueryKind,
    REVOCATION_COLUMNS,
    GraphEntityRow,
    SourceRevisionRow,
    assert_rows_expose_authority_freshness,
    catalog_from_store,
    compile_query,
    evaluate_query,
    get_template,
    is_promotable_trust,
    list_query_kinds,
    project_authority_freshness,
    promote_untrusted_hit,
    required_projection_columns,
    templates_cover_catalog_tables,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    PROOFS_CATALOG_TABLES,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    build_duckdb_proof_store,
    build_unified_proof_key,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _theorem(
    *,
    status: ResultStatus = ResultStatus.PROVED,
    authority: ResultAuthority = ResultAuthority.THEOREM,
    result_id: str = "result:theorem-1",
    backend_id: str = "solver.z3",
    backend_version: str = "4.12.0",
    **changes,
) -> TheoremResult:
    fields = {
        "result_id": result_id,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "authority": authority,
        "status": status,
        "assumptions": ("assumption:int",),
        "bounds": ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "usage": ResourceUsage(
            elapsed_ms=10,
            steps=5,
            peak_memory_bytes=512,
            output_bytes=64,
        ),
        "witness": {"kind": "proof"},
        "diagnostics": (),
        "reason": "",
        "metadata": {},
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _counterexample_result(**changes) -> SatisfiabilityResult:
    """Satisfiable model = counterexample outcome in the proof store."""

    fields = {
        "result_id": "result:cex-1",
        "backend_id": "solver.z3",
        "backend_version": "4.12.0",
        "authority": ResultAuthority.SATISFIABILITY,
        "status": ResultStatus.SATISFIABLE,
        "assumptions": ("assumption:model",),
        "bounds": ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": EvidenceAuthority.BOUNDED,
        "usage": ResourceUsage(
            elapsed_ms=5,
            steps=2,
            peak_memory_bytes=256,
            output_bytes=32,
        ),
        "witness": {"kind": "counterexample", "model": {"x": 1}},
        "diagnostics": (),
        "reason": "",
        "metadata": {},
    }
    fields.update(changes)
    return SatisfiabilityResult(**fields)


def _unified_key(**overrides):
    base = {
        "ir": {"formula": "(assert p)"},
        "property_value": {"property_id": "prop:1"},
        "assumptions": ("assumption:int",),
        "selected_premises": (),
        "translator": {"version": "t1"},
        "solver_identities": ({"solver": "z3"},),
        "toolchain": {"lean": "4.3.0"},
        "theorem_registry": {"registry_hash": "reg:1"},
        "policy": {"mode": "strict"},
        "resources": {"timeout_ms": 1000},
        "tree": {"tree_id": "tree:main"},
        "backend_id": "solver.z3",
        "backend_binary": {"path": "/usr/bin/z3", "sha256": "abc"},
        "backend_version": "4.12.0",
        "backend_config": {"logic": "QF_LIA", "timeout_ms": 1000},
    }
    base.update(overrides)
    return build_unified_proof_key(**base)


def _trusted_entry(
    *,
    key=None,
    created_at: float | None = None,
    non_trusted: bool = False,
    status: ResultStatus = ResultStatus.PROVED,
    premises=(),
    result_id: str = "result:theorem-1",
    entity_id: str | None = None,
    revision: str | None = None,
) -> UnifiedProofEntry:
    key = key or _unified_key(selected_premises=premises)
    result = _theorem(status=status, result_id=result_id)
    if entity_id is not None or revision is not None:
        # Rebuild with metadata embedded via witness/payload path:
        # UnifiedProofEntry.result_payload comes from the typed result.
        meta = dict(result.metadata or {})
        if entity_id is not None:
            meta["entity_id"] = entity_id
        if revision is not None:
            meta["revision"] = revision
        result = _theorem(status=status, result_id=result_id, metadata=meta)
    entry = UnifiedProofEntry.from_typed_result(
        key,
        result,
        created_at=time.time() if created_at is None else float(created_at),
        evidence_authority=(
            EvidenceAuthority.NONE
            if non_trusted
            else EvidenceAuthority.INDEPENDENTLY_CHECKABLE
        ),
        trust_level=(
            ProofTrustLevel.NON_TRUSTED
            if non_trusted
            else ProofTrustLevel.INDEPENDENTLY_CHECKABLE
        ),
        non_trusted=non_trusted,
    )
    return entry


def _counterexample_entry(
    *,
    key=None,
    created_at: float | None = None,
    non_trusted: bool = False,
) -> UnifiedProofEntry:
    key = key or _unified_key(
        ir={"formula": "(assert false-claim)"},
        property_value={"property_id": "prop:cex"},
    )
    result = _counterexample_result()
    return UnifiedProofEntry.from_typed_result(
        key,
        result,
        created_at=time.time() if created_at is None else float(created_at),
        evidence_authority=(
            EvidenceAuthority.NONE
            if non_trusted
            else EvidenceAuthority.BOUNDED
        ),
        trust_level=(
            ProofTrustLevel.NON_TRUSTED
            if non_trusted
            else ProofTrustLevel.BOUNDED
        ),
        non_trusted=non_trusted,
    )


def _catalog_with(*entries: UnifiedProofEntry) -> ProofQueryCatalog:
    catalog = ProofQueryCatalog(
        positive_ttl_seconds=3600.0,
        negative_ttl_seconds=300.0,
    )
    for entry in entries:
        catalog.put_entry(entry)
    return catalog


# ---------------------------------------------------------------------------
# Interface / allowlist pins
# ---------------------------------------------------------------------------


def test_interfaces_and_allowlist_are_pinned() -> None:
    assert DUCKDB_PROOF_QUERIES_INTERFACE == "DuckDBProofQueries@1"
    assert DUCKDB_PROOF_QUERIES_SCHEMA_VERSION == "duckdb-proof-queries/v1"
    kinds = list_query_kinds()
    expected = {
        "proof_hit_miss",
        "premises",
        "dependency_closure",
        "graph_entities",
        "source_revisions",
        "applicability",
        "revocation",
        "counterexamples",
    }
    assert set(kinds) == expected
    assert set(PROOF_QUERY_TEMPLATES) == set(ProofQueryKind)
    for kind in ProofQueryKind:
        template = get_template(kind)
        assert template.kind is kind
        assert template.sql.strip()
        assert "?" in template.sql  # parameterized
        # Every template declares the mandatory projection columns.
        for col in COMMON_PROJECTION_COLUMNS:
            assert col in template.result_columns, (
                f"{kind.value} missing column {col}"
            )


def test_module_import_is_inert_without_duckdb() -> None:
    import importlib

    mod = importlib.import_module(
        "ipfs_datasets_py.logic.common.duckdb_proof_queries"
    )
    assert mod.DUCKDB_PROOF_QUERIES_INTERFACE == "DuckDBProofQueries@1"
    # Must not require duckdb at import time.
    assert "duckdb" not in getattr(mod, "__dict__", {})


def test_unknown_query_kind_rejected() -> None:
    with pytest.raises(ProofQueryError):
        get_template("drop_table")
    with pytest.raises(ProofQueryError):
        compile_query("not_a_template", key_digest="k")


def test_templates_reference_proofs_catalog_tables() -> None:
    covered = templates_cover_catalog_tables()
    # Core tables used by hit/miss, premises, revocation paths.
    assert "proof_entries" in covered
    assert "premises" in covered
    assert "revocations" in covered
    assert covered.issubset(set(PROOFS_CATALOG_TABLES) | covered)


def test_required_projection_columns_cover_acceptance() -> None:
    required = set(required_projection_columns())
    assert set(AUTHORITY_COLUMNS) <= required
    assert set(FRESHNESS_COLUMNS) <= required
    assert set(APPLICABILITY_COLUMNS) <= required
    assert set(REVOCATION_COLUMNS) <= required


# ---------------------------------------------------------------------------
# Hit / miss + no untrusted promotion
# ---------------------------------------------------------------------------


def test_proof_hit_miss_reports_hit_with_authority_freshness() -> None:
    entry = _trusted_entry(created_at=1_000.0)
    catalog = _catalog_with(entry)
    result = evaluate_query(
        catalog,
        ProofQueryKind.PROOF_HIT_MISS,
        key_digest=entry.key.digest,
        now=1_010.0,
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["hit"] is True
    assert row["usable"] is True
    assert row["trust_level"] == ProofTrustLevel.INDEPENDENTLY_CHECKABLE.value
    assert row["fresh"] is True
    assert row["applicable"] is True
    assert row["is_revoked"] is False
    assert row["promotable"] is True
    assert_rows_expose_authority_freshness(result.rows)


def test_proof_miss_is_not_usable_or_promotable() -> None:
    catalog = ProofQueryCatalog()
    missing = content_digest({"missing": True})
    result = evaluate_query(
        catalog,
        "proof_hit_miss",
        key_digest=missing,
        now=100.0,
    )
    row = result.rows[0]
    assert row["hit"] is False
    assert row["usable"] is False
    assert row["promotable"] is False
    assert row["applicable"] is False
    assert row["applicability_reason"] == "miss"
    assert_rows_expose_authority_freshness(result.rows)


def test_untrusted_hit_is_visible_but_not_promotable_or_usable() -> None:
    entry = _trusted_entry(non_trusted=True, created_at=1_000.0)
    catalog = _catalog_with(entry)
    result = evaluate_query(
        catalog,
        ProofQueryKind.PROOF_HIT_MISS,
        key_digest=entry.key.digest,
        now=1_010.0,
    )
    row = result.rows[0]
    assert row["hit"] is True
    assert row["trust_level"] == ProofTrustLevel.NON_TRUSTED.value
    assert row["usable"] is False
    assert row["promotable"] is False
    assert row["applicable"] is False
    assert row["applicability_reason"] == "untrusted"
    # Explicit promotion API must refuse.
    with pytest.raises(ProofQueryError, match="cannot promote an untrusted"):
        promote_untrusted_hit(row)
    with pytest.raises(ProofQueryError, match="cannot promote an untrusted"):
        promote_untrusted_hit(
            row, target_trust=ProofTrustLevel.AUTHORITATIVE
        )


def test_queries_cannot_raise_stored_trust() -> None:
    entry = _trusted_entry(created_at=1_000.0)
    catalog = _catalog_with(entry)
    row = evaluate_query(
        catalog,
        ProofQueryKind.PROOF_HIT_MISS,
        key_digest=entry.key.digest,
        now=1_010.0,
    ).rows[0]
    # Independently checkable cannot be raised to authoritative via query.
    with pytest.raises(ProofQueryError, match="cannot raise trust_level"):
        promote_untrusted_hit(
            row, target_trust=ProofTrustLevel.AUTHORITATIVE
        )
    # Confirming the same level is allowed (no mutation).
    confirmed = promote_untrusted_hit(
        row, target_trust=ProofTrustLevel.INDEPENDENTLY_CHECKABLE
    )
    assert confirmed["trust_level"] == row["trust_level"]


def test_is_promotable_trust_excludes_untrusted() -> None:
    assert is_promotable_trust(ProofTrustLevel.AUTHORITATIVE) is True
    assert is_promotable_trust(ProofTrustLevel.INDEPENDENTLY_CHECKABLE) is True
    assert is_promotable_trust(ProofTrustLevel.BOUNDED) is True
    assert is_promotable_trust(ProofTrustLevel.ADVISORY) is False
    assert is_promotable_trust(ProofTrustLevel.NON_TRUSTED) is False
    assert is_promotable_trust(ProofTrustLevel.NONE) is False
    assert is_promotable_trust("non_trusted") is False


# ---------------------------------------------------------------------------
# Freshness / applicability / revocation always visible
# ---------------------------------------------------------------------------


def test_stale_entry_is_not_fresh_or_applicable() -> None:
    entry = _trusted_entry(created_at=0.0)
    catalog = _catalog_with(entry)
    # positive TTL is 3600; age 10_000 => stale
    result = evaluate_query(
        catalog,
        ProofQueryKind.APPLICABILITY,
        key_digest=entry.key.digest,
        now=10_000.0,
    )
    row = result.rows[0]
    assert row["fresh"] is False
    assert row["applicable"] is False
    assert row["applicability_reason"] == "stale"
    assert row["promotable"] is False
    assert row["is_revoked"] is False
    assert_rows_expose_authority_freshness(result.rows)


def test_revocation_always_visible_and_blocks_applicability() -> None:
    entry = _trusted_entry(created_at=1_000.0)
    catalog = _catalog_with(entry)
    catalog.revoke(
        entry.entry_digest,
        reason="contradicted_by_kernel",
        created_at=1_005.0,
    )
    hit = evaluate_query(
        catalog,
        ProofQueryKind.PROOF_HIT_MISS,
        key_digest=entry.key.digest,
        now=1_010.0,
    ).rows[0]
    assert hit["is_revoked"] is True
    assert hit["revocation_reason"] == "contradicted_by_kernel"
    assert hit["revocation_id"]
    assert hit["applicable"] is False
    assert hit["applicability_reason"] == "revoked"
    assert hit["usable"] is False
    assert hit["promotable"] is False
    assert_rows_expose_authority_freshness([hit])

    revoked = evaluate_query(
        catalog,
        ProofQueryKind.REVOCATION,
        revoked_only=True,
        now=1_010.0,
    )
    assert len(revoked.rows) == 1
    assert revoked.rows[0]["is_revoked"] is True
    assert_rows_expose_authority_freshness(revoked.rows)

    with pytest.raises(ProofQueryError, match="revoked"):
        promote_untrusted_hit(hit)


def test_every_query_kind_exposes_mandatory_columns() -> None:
    parent_premises = (
        content_digest("lemma.a"),
        content_digest("lemma.b"),
    )
    parent = _trusted_entry(
        key=_unified_key(selected_premises=parent_premises),
        created_at=1_000.0,
        result_id="result:parent",
    )
    child_key = _unified_key(
        ir={"formula": "lemma.a"},
        property_value={"property_id": "lemma.a"},
        selected_premises=(content_digest("lemma.a.leaf"),),
    )
    # Force child key digest to equal the premise digest path used by parent:
    # premises are content digests of lemma names, not key digests.  Wire an
    # explicit premise edge in the catalog instead.
    child = _trusted_entry(
        key=child_key,
        created_at=1_000.0,
        result_id="result:child",
        premises=(content_digest("lemma.a.leaf"),),
    )
    cex = _counterexample_entry(created_at=1_000.0)
    catalog = _catalog_with(parent, child, cex)
    # Link parent premise to child key for closure.
    from ipfs_datasets_py.logic.common.duckdb_proof_queries import PremiseRow

    catalog.premises.append(
        PremiseRow(
            key_digest=parent.key.digest,
            premise_digest=child.key.digest,
            premise_ordinal=99,
        )
    )
    catalog.graph_entities.append(
        GraphEntityRow(
            entity_id=parent.key.digest,
            entity_kind="obligation",
            graph_revision="rev:g1",
            source_cid="cid:g1",
        )
    )
    catalog.source_revisions.append(
        SourceRevisionRow(
            revision_id="rev:src-1",
            repository_id="repo:1",
            revision="abc123",
            repository_tree_cid=parent.key.tree_digest,
        )
    )
    catalog.revoke(cex.entry_digest, reason="superseded", created_at=1_001.0)

    now = 1_010.0
    cases = [
        evaluate_query(
            catalog, "proof_hit_miss", key_digest=parent.key.digest, now=now
        ),
        evaluate_query(
            catalog, "premises", key_digest=parent.key.digest, now=now
        ),
        evaluate_query(
            catalog,
            "dependency_closure",
            key_digest=parent.key.digest,
            now=now,
        ),
        evaluate_query(catalog, "graph_entities", now=now),
        evaluate_query(catalog, "source_revisions", now=now),
        evaluate_query(
            catalog, "applicability", key_digest=parent.key.digest, now=now
        ),
        evaluate_query(catalog, "revocation", now=now),
        evaluate_query(catalog, "counterexamples", now=now),
    ]
    for result in cases:
        assert result.rows, f"{result.kind.value} returned no rows"
        assert_rows_expose_authority_freshness(result.rows)
        for row in result.rows:
            # Untrusted promotion must never occur implicitly.
            if row.get("trust_level") in {
                ProofTrustLevel.NON_TRUSTED.value,
                ProofTrustLevel.NONE.value,
            }:
                assert row["promotable"] is False
                assert row.get("usable", False) is False or "usable" not in row


# ---------------------------------------------------------------------------
# Premises + bounded dependency closure
# ---------------------------------------------------------------------------


def test_premises_query_lists_ordered_premises() -> None:
    p1 = content_digest("nat.add_zero")
    p2 = content_digest("nat.succ_inj")
    entry = _trusted_entry(
        key=_unified_key(selected_premises=(p1, p2)),
        created_at=1_000.0,
    )
    catalog = _catalog_with(entry)
    result = evaluate_query(
        catalog,
        ProofQueryKind.PREMISES,
        key_digest=entry.key.digest,
        now=1_010.0,
    )
    digests = [row["premise_digest"] for row in result.rows]
    assert set(digests) == set(entry.key.selected_premise_digests)
    # ordinals are non-decreasing
    ordinals = [row["premise_ordinal"] for row in result.rows]
    assert ordinals == sorted(ordinals)
    assert_rows_expose_authority_freshness(result.rows)


def test_dependency_closure_is_depth_and_row_bounded() -> None:
    # Build a chain A -> B -> C -> D via premise digests == child key digests.
    keys = []
    digests_chain: list[str] = []
    # Pre-create leaf first so we can wire digests bottom-up.
    leaf = _trusted_entry(
        key=_unified_key(
            ir={"formula": "leaf"},
            property_value={"property_id": "leaf"},
            selected_premises=(),
        ),
        created_at=1_000.0,
        result_id="result:leaf",
    )
    digests_chain.append(leaf.key.digest)
    keys.append(leaf)

    prev = leaf.key.digest
    for name in ("c", "b", "a"):
        node = _trusted_entry(
            key=_unified_key(
                ir={"formula": name},
                property_value={"property_id": name},
                selected_premises=(),
            ),
            created_at=1_000.0,
            result_id=f"result:{name}",
        )
        keys.append(node)
        digests_chain.append(node.key.digest)
        prev = node.key.digest

    catalog = _catalog_with(*keys)
    # Wire chain: a -> b -> c -> leaf by premise rows.
    # keys order: leaf, c, b, a
    from ipfs_datasets_py.logic.common.duckdb_proof_queries import PremiseRow

    catalog.premises.clear()
    catalog.premises.extend(
        [
            PremiseRow(
                key_digest=keys[3].key.digest,  # a
                premise_digest=keys[2].key.digest,  # b
                premise_ordinal=0,
            ),
            PremiseRow(
                key_digest=keys[2].key.digest,  # b
                premise_digest=keys[1].key.digest,  # c
                premise_ordinal=0,
            ),
            PremiseRow(
                key_digest=keys[1].key.digest,  # c
                premise_digest=keys[0].key.digest,  # leaf
                premise_ordinal=0,
            ),
        ]
    )

    shallow = evaluate_query(
        catalog,
        ProofQueryKind.DEPENDENCY_CLOSURE,
        key_digest=keys[3].key.digest,
        now=1_010.0,
        budget=ProofQueryBudget(max_depth=1, max_rows=100),
    )
    assert shallow.depth_reached <= 1
    assert all(row["depth"] <= 1 for row in shallow.rows)
    assert_rows_expose_authority_freshness(shallow.rows)

    full = evaluate_query(
        catalog,
        ProofQueryKind.DEPENDENCY_CLOSURE,
        key_digest=keys[3].key.digest,
        now=1_010.0,
        budget=ProofQueryBudget(max_depth=8, max_rows=100),
    )
    assert full.depth_reached >= 3
    reached = {row["premise_digest"] for row in full.rows}
    assert keys[2].key.digest in reached
    assert keys[0].key.digest in reached

    row_limited = evaluate_query(
        catalog,
        ProofQueryKind.DEPENDENCY_CLOSURE,
        key_digest=keys[3].key.digest,
        now=1_010.0,
        budget=ProofQueryBudget(max_depth=8, max_rows=1),
    )
    assert len(row_limited.rows) <= 1
    assert row_limited.truncated is True


def test_dependency_closure_time_budget_enforced() -> None:
    # Fan-out graph large enough that a tiny time budget trips.
    from ipfs_datasets_py.logic.common.duckdb_proof_queries import PremiseRow

    root = _trusted_entry(
        key=_unified_key(
            ir={"formula": "root"},
            property_value={"property_id": "root"},
        ),
        created_at=1_000.0,
        result_id="result:root",
    )
    catalog = _catalog_with(root)
    # Many premise edges from root (no recursion needed to trip time if
    # max_seconds is near zero — the loop still checks the clock).
    for i in range(50):
        catalog.premises.append(
            PremiseRow(
                key_digest=root.key.digest,
                premise_digest=content_digest(f"p:{i}"),
                premise_ordinal=i,
            )
        )
    with pytest.raises(ProofQueryBudgetExceeded) as exc:
        evaluate_query(
            catalog,
            ProofQueryKind.DEPENDENCY_CLOSURE,
            key_digest=root.key.digest,
            now=1_010.0,
            budget=ProofQueryBudget(max_depth=8, max_rows=10_000, max_seconds=1e-12),
        )
    assert exc.value.kind == "time"


def test_budget_validation() -> None:
    with pytest.raises(ProofQueryError):
        ProofQueryBudget(max_depth=-1)
    with pytest.raises(ProofQueryError):
        ProofQueryBudget(max_rows=0)
    with pytest.raises(ProofQueryError):
        ProofQueryBudget(max_seconds=0)
    with pytest.raises(ProofQueryError):
        ProofQueryBudget(max_depth=1000)


# ---------------------------------------------------------------------------
# Graph entities, source revisions, counterexamples
# ---------------------------------------------------------------------------


def test_graph_entities_join() -> None:
    entry = _trusted_entry(created_at=1_000.0)
    catalog = _catalog_with(entry)
    catalog.graph_entities.append(
        GraphEntityRow(
            entity_id=entry.key.digest,
            entity_kind="lemma",
            graph_revision="rev:42",
            source_cid="cid:42",
        )
    )
    result = evaluate_query(
        catalog,
        ProofQueryKind.GRAPH_ENTITIES,
        key_digest=entry.key.digest,
        graph_revision="rev:42",
        now=1_010.0,
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["entity_id"] == entry.key.digest
    assert row["entity_kind"] == "lemma"
    assert row["graph_revision"] == "rev:42"
    assert row["trust_level"]
    assert "is_revoked" in row
    assert "fresh" in row
    assert "applicable" in row


def test_source_revisions_join() -> None:
    entry = _trusted_entry(created_at=1_000.0)
    catalog = _catalog_with(entry)
    catalog.source_revisions.append(
        SourceRevisionRow(
            revision_id="rev:src-9",
            repository_id="repo:datasets",
            revision="deadbeef",
            repository_tree_cid=entry.key.tree_digest,
        )
    )
    result = evaluate_query(
        catalog,
        ProofQueryKind.SOURCE_REVISIONS,
        key_digest=entry.key.digest,
        now=1_010.0,
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["revision_id"] == "rev:src-9"
    assert row["repository_tree_cid"] == entry.key.tree_digest
    assert_rows_expose_authority_freshness(result.rows)


def test_counterexamples_query_filters_outcome() -> None:
    proof = _trusted_entry(created_at=1_000.0, result_id="result:proof")
    cex = _counterexample_entry(created_at=1_000.0)
    catalog = _catalog_with(proof, cex)
    result = evaluate_query(
        catalog,
        ProofQueryKind.COUNTEREXAMPLES,
        now=1_010.0,
    )
    assert len(result.rows) == 1
    assert result.rows[0]["outcome"] == ProofOutcomeKind.COUNTEREXAMPLE.value
    assert result.rows[0]["key_digest"] == cex.key.digest
    assert_rows_expose_authority_freshness(result.rows)


# ---------------------------------------------------------------------------
# Compile path (SQL templates parameterized)
# ---------------------------------------------------------------------------


def test_compile_query_is_parameterized_and_never_interpolates() -> None:
    compiled = compile_query(
        ProofQueryKind.PROOF_HIT_MISS,
        key_digest=content_digest("k"),
        now=42.0,
        positive_ttl_seconds=100.0,
        negative_ttl_seconds=10.0,
    )
    assert compiled.kind is ProofQueryKind.PROOF_HIT_MISS
    assert "?" in compiled.sql
    assert "DROP" not in compiled.sql.upper()
    # Digest appears only in bound parameters, not SQL text.
    digest = content_digest("k")
    assert digest not in compiled.sql
    assert digest in compiled.parameters
    assert set(COMMON_PROJECTION_COLUMNS) <= set(compiled.result_columns)


def test_compile_dependency_closure_binds_depth_and_rows() -> None:
    compiled = compile_query(
        ProofQueryKind.DEPENDENCY_CLOSURE,
        key_digest=content_digest("root"),
        budget=ProofQueryBudget(max_depth=3, max_rows=25),
        now=1.0,
    )
    assert compiled.budget is not None
    assert compiled.budget.max_depth == 3
    assert 3 in compiled.parameters
    assert 25 in compiled.parameters


def test_compile_requires_key_digest_where_needed() -> None:
    with pytest.raises(ProofQueryError, match="key_digest"):
        compile_query(ProofQueryKind.PREMISES)
    with pytest.raises(ProofQueryError, match="key_digest"):
        compile_query(ProofQueryKind.APPLICABILITY)


# ---------------------------------------------------------------------------
# Store integration helper
# ---------------------------------------------------------------------------


def test_catalog_from_store_and_hit_path() -> None:
    store = build_duckdb_proof_store(
        positive_ttl_seconds=3600.0,
        negative_ttl_seconds=300.0,
    )
    entry = _trusted_entry(created_at=time.time())
    store.put(entry)
    catalog = catalog_from_store(store)
    result = evaluate_query(
        catalog,
        ProofQueryKind.PROOF_HIT_MISS,
        key_digest=entry.key.digest,
        now=time.time(),
    )
    assert result.rows[0]["hit"] is True
    assert result.rows[0]["usable"] is True


def test_project_authority_freshness_never_promotes_untrusted() -> None:
    projected = project_authority_freshness(
        trust_level=ProofTrustLevel.NON_TRUSTED,
        result_authority="candidate",
        evidence_authority="none",
        polarity=CachePolarity.POSITIVE,
        created_at=0.0,
        now=1.0,
        positive_ttl_seconds=100.0,
        negative_ttl_seconds=10.0,
        revocation=None,
    )
    assert projected["promotable"] is False
    assert projected["applicable"] is False
    assert projected["applicability_reason"] == "untrusted"
    assert projected["trust_level"] == "non_trusted"
    assert projected["fresh"] is True
    for col in COMMON_PROJECTION_COLUMNS:
        assert col in projected
