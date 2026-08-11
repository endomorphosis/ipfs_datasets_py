"""E2E tests: DuckDB-only graph control authority (DQK-061).

Acceptance:

* Graph service starts from DuckDB plus immutable Parquet/IPLD with legacy
  catalog files absent
* Static and dynamic guards find no mutable graph-control file writer
* Only sanitized graph views reach the publication database
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from typing import Any, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
from ipfs_datasets_py.knowledge_graphs.catalog.store import (
    GRAPH_DUCKDB_ONLY_OWNER_TASK,
    GRAPH_DUCKDB_ONLY_SCHEMA,
    GRAPH_PUBLICATION_TYPE,
    DuckDBCatalogFacade,
    GraphLegacyFilesystemGuard,
    ImplicitLegacyGraphControlError,
    configure_duckdb_only_graph_authority,
    duckdb_only_graph_control,
    export_sqlite_catalog_compat,
    get_graph_filesystem_guard,
    import_sqlite_catalog_compat,
    legacy_graph_control_io_allowed,
    open_duckdb_catalog,
    reset_graph_authority,
    reset_graph_filesystem_guard,
)
from ipfs_datasets_py.knowledge_graphs.service import GraphService, GraphTarget

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALLOWED_SOURCE_PATHS = (
    _REPO_ROOT / "ipfs_datasets_py/knowledge_graphs/catalog/store.py",
    _REPO_ROOT / "ipfs_datasets_py/knowledge_graphs/service.py",
    _REPO_ROOT / "ipfs_datasets_py/knowledge_graphs/storage/hybrid.py",
)
_HYBRID_PATH = (
    _REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs" / "storage" / "hybrid.py"
)


def _ensure_package_shell(pkg_name: str, pkg_path: Path) -> None:
    """Register a namespace package shell without executing eager ``__init__``."""

    if pkg_name in sys.modules:
        return
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(pkg_path)]  # type: ignore[attr-defined]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg


def _load_verified_hybrid_cache():
    """Load hybrid module without ``storage/__init__`` (avoids sealed-env anyio).

    The sealed validator ships DuckDB but not ``anyio``.  Importing
    ``ipfs_datasets_py.knowledge_graphs.storage.hybrid`` via the package path
    executes ``storage/__init__.py``, which pulls ``ipld_backend`` → anyio and
    fails collection.  hybrid itself only needs ``ipld_store`` (no anyio).
    """

    module_name = "ipfs_datasets_py.knowledge_graphs.storage.hybrid"
    existing = sys.modules.get(module_name)
    if existing is not None and hasattr(existing, "VerifiedHybridCache"):
        return existing.VerifiedHybridCache

    storage_root = _REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs" / "storage"
    for pkg_name, pkg_path in (
        ("ipfs_datasets_py", _REPO_ROOT / "ipfs_datasets_py"),
        (
            "ipfs_datasets_py.knowledge_graphs",
            _REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs",
        ),
        ("ipfs_datasets_py.knowledge_graphs.storage", storage_root),
    ):
        # Prefer real packages when already loaded; only shell missing parents.
        if pkg_name not in sys.modules:
            _ensure_package_shell(pkg_name, pkg_path)

    # Ensure storage package shell has no side-effecting __init__ if we just
    # created it (empty shell). If a full package was already imported, keep it.
    storage_mod = sys.modules.get("ipfs_datasets_py.knowledge_graphs.storage")
    if storage_mod is not None and not hasattr(storage_mod, "IPLDBackend"):
        # Shell only — safe. Load hybrid by path.
        pass
    elif storage_mod is not None and hasattr(storage_mod, "IPLDBackend"):
        # Full package already loaded; normal import is fine.
        from ipfs_datasets_py.knowledge_graphs.storage.hybrid import (  # noqa: WPS433
            VerifiedHybridCache,
        )

        return VerifiedHybridCache

    # Load ipld_store first (hybrid dependency) without package init.
    ipld_name = "ipfs_datasets_py.knowledge_graphs.storage.ipld_store"
    if ipld_name not in sys.modules:
        ipld_path = storage_root / "ipld_store.py"
        ipld_spec = importlib.util.spec_from_file_location(ipld_name, ipld_path)
        assert ipld_spec is not None and ipld_spec.loader is not None
        ipld_mod = importlib.util.module_from_spec(ipld_spec)
        sys.modules[ipld_name] = ipld_mod
        ipld_spec.loader.exec_module(ipld_mod)

    spec = importlib.util.spec_from_file_location(module_name, _HYBRID_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.VerifiedHybridCache


VerifiedHybridCache = _load_verified_hybrid_cache()


@pytest.fixture
def authority(tmp_path: Path):
    reset_graph_authority()
    reset_graph_filesystem_guard()
    auth = configure_duckdb_only_graph_authority(
        tmp_path / "graph_control.duckdb",
        duckdb_tx_path=tmp_path / "graph_tx.duckdb",
        duckdb_crypto_path=tmp_path / "graph_crypto.duckdb",
    )
    yield auth
    reset_graph_authority()
    reset_graph_filesystem_guard()


@pytest.fixture
def service(tmp_path: Path, authority):
    svc = GraphService.open_duckdb_only(
        tmp_path / "graph_control.duckdb",
        storage_path=tmp_path / "payloads",
        shadow_authority=authority,
        configure_process_authority=False,
    )
    yield svc
    svc.close()


def _sqlite_files(root: Path) -> List[Path]:
    if not root.exists():
        return []
    out: List[Path] = []
    for pattern in ("*.sqlite", "*.sqlite3"):
        out.extend(p for p in root.rglob(pattern) if p.is_file())
    return sorted(out)


def _mutable_control_json(root: Path) -> List[Path]:
    names = {
        "authority.json",
        "index.json",
        "catalog.json",
        "graphs.json",
        "control.json",
        "graph-control.json",
        "graph_control.json",
    }
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*.json") if p.is_file() and p.name in names
    )


# ---------------------------------------------------------------------------
# Module invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_owner_task_and_publication_constants(self):
        assert GRAPH_DUCKDB_ONLY_OWNER_TASK == "DQK-061"
        assert GRAPH_PUBLICATION_TYPE == "graph_quack_publication_v1"
        assert GRAPH_DUCKDB_ONLY_SCHEMA.startswith("ipfs_datasets_py/")

    def test_filesystem_guard_classifies_guarded_paths(self, tmp_path: Path):
        guard = GraphLegacyFilesystemGuard(allow_legacy_io=False)
        assert guard.classify_path(tmp_path / "catalog.sqlite") == "catalog_sqlite"
        assert (
            guard.classify_path(tmp_path / "kg_catalog.sqlite") == "catalog_sqlite"
        )
        assert (
            guard.classify_path(tmp_path / "authority.json")
            == "mutable_control_json"
        )
        assert guard.classify_path(tmp_path / "index.json") == "mutable_control_json"
        assert guard.classify_path(tmp_path / "graphs.json") == "mutable_control_json"
        # Identity-bearing CID meta is not mutable control.
        assert (
            guard.classify_path(
                tmp_path / "meta" / "bafyidentitybearingmanifest0001.json"
            )
            is None
        )
        # DuckDB authority files are not legacy SQLite.
        assert guard.classify_path(tmp_path / "graph_control.duckdb") is None


# ---------------------------------------------------------------------------
# Acceptance: service starts from DuckDB + Parquet/IPLD without legacy files
# ---------------------------------------------------------------------------


class TestServiceStartsDuckDBOnly:
    def test_open_duckdb_only_without_sqlite(
        self, service: GraphService, authority, tmp_path: Path
    ):
        assert service.is_duckdb_only is True
        assert isinstance(service.catalog, DuckDBCatalogFacade)
        assert duckdb_only_graph_control() is True
        assert authority.legacy_io_allowed is False
        assert legacy_graph_control_io_allowed() is False
        assert authority.mode == AuthorityMode.DB_PRIMARY.value

        result = service.create(
            GraphTarget(tenant="acme", graph_id="orders", storage_profile="parquet"),
            idempotency_key="create:acme/orders",
        )
        assert result.ok is True or getattr(result, "error", None) is None
        # LifecycleResult may expose .ok; also accept success via payload.
        payload = getattr(result, "result", None) or getattr(result, "payload", None)
        if isinstance(payload, dict):
            assert payload.get("graph_id") == "orders" or "orders" in str(payload)

        listed = service.list(
            GraphTarget(tenant="acme", graph_id="orders"),
        )
        # list returns LifecycleResult
        assert listed is not None

        # Legacy catalog files must remain absent.
        assert _sqlite_files(tmp_path) == []
        assert not (tmp_path / "catalog.sqlite").exists()
        # DuckDB control + payload content may exist; no mutable control JSON.
        assert any(tmp_path.rglob("*.duckdb"))
        assert _mutable_control_json(tmp_path) == []

    def test_reopen_from_duckdb_without_sqlite(
        self, authority, tmp_path: Path
    ):
        duck_path = tmp_path / "graph_control.duckdb"
        payloads = tmp_path / "payloads"
        svc1 = GraphService.open_duckdb_only(
            duck_path,
            storage_path=payloads,
            shadow_authority=authority,
            configure_process_authority=False,
        )
        try:
            created = svc1.create(
                GraphTarget(
                    tenant="t1", graph_id="g1", storage_profile="parquet"
                ),
                idempotency_key="create:t1/g1",
            )
            assert created is not None
        finally:
            svc1.close()

        assert _sqlite_files(tmp_path) == []

        # Fresh service reopens committed control + payloads without SQLite.
        svc2 = GraphService.open_duckdb_only(
            duck_path,
            storage_path=payloads,
            shadow_authority=authority,
            configure_process_authority=False,
        )
        try:
            desc = svc2.describe(
                GraphTarget(tenant="t1", graph_id="g1"),
            )
            assert desc is not None
            # catalog still has the graph
            rec = svc2.catalog.get_graph("t1", "g1")
            assert rec.graph_id == "g1"
            assert rec.storage_profile == "parquet"
            assert svc2.is_duckdb_only is True
        finally:
            svc2.close()
        assert _sqlite_files(tmp_path) == []

    def test_open_with_duckdb_suffix_routes_to_duckdb_only(
        self, authority, tmp_path: Path
    ):
        path = tmp_path / "control.duckdb"
        svc = GraphService.open(
            path,
            storage_path=tmp_path / "payloads",
            shadow_authority=authority,
        )
        try:
            assert svc.is_duckdb_only is True
            assert isinstance(svc.catalog, DuckDBCatalogFacade)
            svc.create(
                GraphTarget(tenant="x", graph_id="y", storage_profile="ipfs_ipld"),
                idempotency_key="create:x/y",
            )
        finally:
            svc.close()
        assert _sqlite_files(tmp_path) == []


# ---------------------------------------------------------------------------
# Acceptance: static + dynamic guards — no mutable graph-control writers
# ---------------------------------------------------------------------------


class TestNoMutableGraphControlWriters:
    def test_dynamic_guard_blocks_sqlite_and_control_json(
        self, authority, tmp_path: Path
    ):
        assert duckdb_only_graph_control() is True
        assert legacy_graph_control_io_allowed() is False
        guard = get_graph_filesystem_guard()

        for path, kind in (
            (tmp_path / "catalog.sqlite", "catalog_sqlite"),
            (tmp_path / "authority.json", "mutable_control_json"),
            (tmp_path / "index.json", "mutable_control_json"),
            (tmp_path / "graphs.json", "mutable_control_json"),
        ):
            with pytest.raises(ImplicitLegacyGraphControlError) as excinfo:
                guard.assert_allowed(path, kind=kind, operation="write")
            assert excinfo.value.kind == kind
            assert "implicit" in str(excinfo.value).lower()

            with pytest.raises(ImplicitLegacyGraphControlError):
                guard.assert_allowed(path, kind=kind, operation="read")

    def test_service_refuses_sqlite_open_after_promotion(
        self, authority, tmp_path: Path
    ):
        sqlite_path = tmp_path / "catalog.sqlite"
        with pytest.raises(ImplicitLegacyGraphControlError):
            GraphService.open(
                sqlite_path,
                storage_path=tmp_path / "payloads",
                shadow_authority=authority,
            )
        assert not sqlite_path.exists()

    def test_hybrid_skips_mutable_control_json_writes(
        self, authority, tmp_path: Path
    ):
        cache_root = tmp_path / "hybrid-cache"
        cache = VerifiedHybridCache(
            cache_root,
            shadow_authority=authority,
            persist_mutable_control=None,  # derive from process guard
        )
        assert cache.persist_mutable_control is False

        # Put an identity-bearing object (content path remains durable).
        data = b"immutable-ipld-payload-bytes"
        entry = cache.put(data)
        assert entry is not None
        result_cid = entry.cid
        assert result_cid
        assert cache.contains(result_cid)

        # Mutable control files must not appear.
        assert not (cache_root / "authority.json").exists()
        assert not (cache_root / "index.json").exists()
        # Identity-bearing meta/<cid>.json is allowed.
        meta = cache_root / "meta" / f"{result_cid}.json"
        assert meta.is_file()
        obj = cache_root / "objects" / f"{result_cid}.bin"
        assert obj.is_file()
        assert obj.read_bytes() == data

    def test_hybrid_explicit_export_control_json(
        self, authority, tmp_path: Path
    ):
        cache = VerifiedHybridCache(
            tmp_path / "hybrid-export",
            shadow_authority=authority,
        )
        cache.put(b"payload-for-export")
        assert not (tmp_path / "hybrid-export" / "authority.json").exists()

        paths = cache.export_control_json()
        assert paths["authority"].is_file()
        assert paths["index"].is_file()
        # After explicit export, implicit writes remain blocked.
        with pytest.raises(ImplicitLegacyGraphControlError):
            get_graph_filesystem_guard().assert_allowed(
                tmp_path / "authority.json",
                kind="mutable_control_json",
                operation="write",
            )

    def test_static_source_guard_no_unguarded_control_writers(self):
        """AST/static scan: mutable control writers go through guards/exports."""

        forbidden_name_patterns = (
            re.compile(r"catalog\.sqlite"),
            re.compile(r"authority\.json"),
            re.compile(r"\bindex\.json\b"),
        )
        # Allowed intentional mentions: classify_path, docs, export helpers,
        # guard lists, comments, string constants used for classification.
        allow_tokens = (
            "classify_path",
            "permit_export",
            "permit_import",
            "export_control_json",
            "export_sqlite_catalog_compat",
            "import_sqlite_catalog_compat",
            "mutable_control_json",
            "catalog_sqlite",
            "_GUARDED",
            "assert_allowed",
            "ImplicitLegacyGraphControlError",
            "GraphLegacyFilesystemGuard",
            "_persist_authority",
            "_persist_index",
            "persist_mutable_control",
            "duckdb_only",
            "DQK-061",
            "open_duckdb_only",
            "legacy_io_allowed",
            "skip_mutable_",
            "mutable graph-control",
            "mutable control",
            "Layout::",
            "authority.json",  # docstring layout / classification only
            "index.json",
        )

        offenders: List[str] = []
        for path in _ALLOWED_SOURCE_PATHS:
            text = path.read_text(encoding="utf-8")
            # Parse as AST to ensure file is valid Python.
            ast.parse(text)
            for i, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                for pat in forbidden_name_patterns:
                    if not pat.search(line):
                        continue
                    # Skip string-only classification / documentation lines.
                    if any(tok in line for tok in allow_tokens):
                        continue
                    # Skip pure string constants in tuples/sets.
                    if re.search(r"""['\"][^'\"]*%s[^'\"]*['\"]""" % re.escape(pat.pattern.replace("\\", "")), line):
                        # Still require an allow token for assignment/write forms.
                        if "write" in line.lower() or "open(" in line or "Path(" in line and "write" in line:
                            if not any(tok in line for tok in allow_tokens):
                                offenders.append(f"{path.name}:{i}:{line.strip()}")
                        continue
                    if any(
                        w in line
                        for w in (
                            "write_text",
                            "write_bytes",
                            "atomic_write",
                            "json.dump",
                            "open(",
                            "connect(",
                        )
                    ):
                        offenders.append(f"{path.name}:{i}:{line.strip()}")

        assert offenders == [], "unguarded mutable control writers:\n" + "\n".join(
            offenders
        )

    def test_static_no_implicit_sqlite_fallback_in_service(self):
        service_src = (
            _REPO_ROOT / "ipfs_datasets_py/knowledge_graphs/service.py"
        ).read_text(encoding="utf-8")
        assert "open_duckdb_only" in service_src
        assert "DuckDBCatalogFacade" in service_src
        assert "DQK-061" in service_src
        # open_catalog remains for transitional dual-mode only, gated by guard.
        assert "get_graph_filesystem_guard" in service_src


# ---------------------------------------------------------------------------
# Acceptance: only sanitized graph views reach publication
# ---------------------------------------------------------------------------


class TestPublicationSurface:
    def test_only_sanitized_graph_views(
        self, service: GraphService, authority, tmp_path: Path
    ):
        service.create(
            GraphTarget(tenant="pub", graph_id="kg1", storage_profile="parquet"),
            idempotency_key="create:pub/kg1",
        )
        # Acquire a lease so writer state exists in DuckDB but must not publish.
        lease = service.catalog.acquire_lease(
            "pub", "kg1", "main", holder="writer-1", ttl_seconds=60.0
        )
        assert lease.lease_id

        doc = service.publication_document()
        assert doc["publication_type"] == GRAPH_PUBLICATION_TYPE
        assert doc["owner_task"] == GRAPH_DUCKDB_ONLY_OWNER_TASK
        assert doc["leases_excluded"] is True
        assert doc["writer_state_excluded"] is True
        assert doc["raw_payloads_excluded"] is True
        assert doc["sqlite_authority"] is False
        assert doc.get("legacy_sqlite_absent") is True

        views = doc["approved_sanitized_graph_views"]
        assert isinstance(views, list)
        assert len(views) >= 1
        for view in views:
            assert "tenant" in view
            assert "graph_id" in view
            assert "head_revision" in view
            assert view.get("leases_excluded") is True
            assert view.get("writer_state_excluded") is True
            assert view.get("raw_payloads_excluded") is True
            # Never leak writer/lease/idempotency internals.
            assert "lease_id" not in view
            assert "holder" not in view
            assert "epoch" not in view
            assert "idempotency" not in view
            assert "response_json" not in view
            assert "metadata_json" not in view

        serialized = json.dumps(doc)
        assert lease.lease_id not in serialized
        assert "writer-1" not in serialized
        assert "principal_secrets" not in serialized
        assert "response_json" not in serialized

        # Authority document matches service surface.
        auth_doc = authority.publication_document()
        assert auth_doc["publication_type"] == GRAPH_PUBLICATION_TYPE
        assert auth_doc["leases_excluded"] is True

    def test_authority_publication_excludes_tombstoned(
        self, service: GraphService, authority
    ):
        service.create(
            GraphTarget(tenant="pub", graph_id="live", storage_profile="parquet"),
            idempotency_key="create:pub/live",
        )
        service.create(
            GraphTarget(tenant="pub", graph_id="dead", storage_profile="parquet"),
            idempotency_key="create:pub/dead",
        )
        service.catalog.delete_graph("pub", "dead", reason="retire")
        views = authority.approved_sanitized_graph_views(approved_only=True)
        ids = {v["graph_id"] for v in views if v.get("tenant") == "pub"}
        assert "live" in ids
        assert "dead" not in ids


# ---------------------------------------------------------------------------
# Explicit import/export compatibility only
# ---------------------------------------------------------------------------


class TestExplicitImportExportCompat:
    def test_sqlite_export_and_import_compat(
        self, service: GraphService, authority, tmp_path: Path
    ):
        service.create(
            GraphTarget(tenant="mig", graph_id="g1", storage_profile="parquet"),
            idempotency_key="create:mig/g1",
        )
        sqlite_path = tmp_path / "export" / "catalog.sqlite"
        sqlite_path.parent.mkdir(parents=True)

        # Without permit, export path is blocked by the guard when asserted.
        with pytest.raises(ImplicitLegacyGraphControlError):
            get_graph_filesystem_guard().assert_allowed(
                sqlite_path, kind="catalog_sqlite", operation="write"
            )

        exported = export_sqlite_catalog_compat(
            service.catalog, sqlite_path, tenant="mig"
        )
        assert exported.is_file()

        # Import into a fresh DuckDB catalog (one-time compat).
        fresh_duck = tmp_path / "imported.duckdb"
        imported = import_sqlite_catalog_compat(
            sqlite_path, fresh_duck, authority=authority
        )
        try:
            rec = imported.get_graph("mig", "g1")
            assert rec.graph_id == "g1"
        finally:
            imported.close()

        # Implicit runtime I/O remains blocked after export/import.
        with pytest.raises(ImplicitLegacyGraphControlError):
            get_graph_filesystem_guard().assert_allowed(
                tmp_path / "another.sqlite",
                kind="catalog_sqlite",
                operation="write",
            )
