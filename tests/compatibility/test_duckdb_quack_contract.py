"""Hermetic Quack protocol and upgrade compatibility suite (DQK-050).

Acceptance coverage:

* local / stateless / attached sessions, transactions, large fetches
* known attached UPDATE/DELETE and ALTER gaps (workarounds or hard gates)
* rollback behavior and crashed-client resource cleanup
* fresh-connection authentication hooks and exact full-SQL authorization
* extension pinning and upgrade refusal against the exact DQK-084 DuckLake
  capability profile
* DuckLake-over-Quack contract slice:
  - one server-owned catalog serves concurrent remote snapshot readers without
    shared-session drift
  - one authorized remote mutation reports the expected last committed snapshot
  - cancellation / lost fetch releases server state
  - prepared parameters remain separate from the exact authorization template
  - internal DuckLake metadata/file-key functions plus SHOW/duckdb_*,
    SET/RESET/PRAGMA/COPY/read_*/network surfaces remain unreachable
* Quack beta use and DuckDB 2.0 adoption each require an explicit
  compatibility and risk/requalification receipt
* DuckLake-over-Quack snapshot reads, mutations, cancellation, authentication,
  parameterization, and internal-surface denial pass before DQK-104
* Server/client/extension mismatch fails before mutation

Live DuckDB / Quack / network are never required.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# Prefer the sealed validator's accelerator checkout in nested worktrees.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_CONTRACT_PATH = (
    _REPO_ROOT / "scripts/validation/validate_duckdb_quack_compatibility.py"
)


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
        # Fall back to admitted root env / common layout.
        for candidate in (
            Path(
                os.environ.get(
                    "IPFS_ACCELERATE_AGENT_ADMITTED_ACCELERATE_ROOT",
                    "",
                )
            ),
            _REPO_ROOT.parents[3] / "ipfs_accelerate_py"
            if len(_REPO_ROOT.parents) >= 4
            else Path(),
            Path("/home/barberb/lift_coding/.worktrees/ipfs-datasets-duckdb-quack")
            / "ipfs_accelerate_py",
        ):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            runtime = (
                resolved
                / "ipfs_accelerate_py"
                / "agent_supervisor"
                / "validation_runtime.py"
            )
            if runtime.is_file():
                accelerate_paths.append(resolved)
                break
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

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_contract_module() -> ModuleType:
    """Load the validation script without requiring scripts.validation package.

    ``scripts/validation`` is not a package (and this task cannot add
    ``__init__.py``), so we load the module by absolute path and register it
    under a stable name for dataclasses / re-imports.
    """

    module_name = "validate_duckdb_quack_compatibility"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "CONTRACT_TASK_ID", None) == "DQK-050":
        return existing
    spec = importlib.util.spec_from_file_location(module_name, _CONTRACT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load contract module from {_CONTRACT_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass and relative lookups see the module.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


from ipfs_datasets_py.duckdb_control import capabilities as control_caps
from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake import capabilities as lake_caps

contract = _load_contract_module()


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_contract_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("validate_duckdb_quack_compatibility", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    mod = _load_contract_module()
    assert mod.COMPATIBILITY_CONTRACT_SCHEMA.startswith("ipfs_datasets_py/")
    assert mod.CONTRACT_TASK_ID == "DQK-050"
    assert mod.PRE_DQK_104_GATE == "DQK-104"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server(**kwargs: Any) -> contract.CatalogOwnerServer:
    return contract.CatalogOwnerServer(**kwargs)


def _open(
    server: contract.CatalogOwnerServer,
    *,
    kind: contract.SessionKind,
    template: str,
    operation_id: str = "op",
    snapshot: int | None = None,
    client_profile: contract.CompatibilityProfile | None = None,
) -> contract.SessionState:
    cap = server.mint_capability(
        operation_id=operation_id,
        authorization_template=template,
    )
    return server.open_session(
        session_kind=kind,
        capability_secret=cap.secret,
        selected_snapshot=snapshot,
        client_profile=client_profile,
    )


# ---------------------------------------------------------------------------
# Local / stateless / attached sessions
# ---------------------------------------------------------------------------


def test_local_stateless_and_attached_sessions_open_and_isolate() -> None:
    server = _server()
    sessions: dict[contract.SessionKind, contract.SessionState] = {}
    for kind in contract.SessionKind:
        template = f"SELECT 1 /* {kind.value} */"
        sessions[kind] = _open(
            server,
            kind=kind,
            template=template,
            operation_id=f"op-{kind.value}",
        )

    ids = {s.session_id for s in sessions.values()}
    assert len(ids) == 3
    for kind, sess in sessions.items():
        assert sess.session_kind is kind
        assert sess.closed is False
        assert sess.selected_snapshot == server.last_committed_snapshot
        public = server.session_public_state(sess.session_id)
        assert public["session_kind"] == kind.value

    # Closing one session does not affect others.
    server.close_session(sessions[contract.SessionKind.LOCAL].session_id)
    with pytest.raises(contract.SessionError, match="unknown or closed"):
        server.session_public_state(sessions[contract.SessionKind.LOCAL].session_id)
    assert (
        server.session_public_state(
            sessions[contract.SessionKind.STATELESS].session_id
        )["closed"]
        is False
    )


def test_fresh_connection_authentication_hook_is_one_use() -> None:
    server = _server()
    template = "SELECT 1"
    cap = server.mint_capability(
        operation_id="op-auth",
        authorization_template=template,
    )
    sess = server.open_session(
        session_kind=contract.SessionKind.STATELESS,
        capability_secret=cap.secret,
    )
    assert sess.authenticated.capability_id == cap.capability_id
    # Reuse of the same secret fails closed.
    with pytest.raises(qs.AuthenticationError):
        server.open_session(
            session_kind=contract.SessionKind.STATELESS,
            capability_secret=cap.secret,
        )


def test_exact_full_sql_authorization() -> None:
    server = _server()
    template = "INSERT INTO lake.t (id, name) VALUES ($id, $name)"
    sess = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=template,
        operation_id="op-authz",
    )
    # Exact template authorizes.
    assert server.authorize_only(sess.session_id, template) is True
    # Prefix / drifted SQL denied.
    with pytest.raises(qs.AuthorizationError):
        server.authorize_only(sess.session_id, "INSERT INTO lake.t (id, name) VALUES")
    with pytest.raises(qs.AuthorizationError):
        server.authorize_only(sess.session_id, template + " -- smuggled")
    with pytest.raises(qs.AuthorizationError, match="unknown"):
        server.authorize_only("sess_missing", template)


# ---------------------------------------------------------------------------
# Transactions, rollback, large fetches, crash cleanup
# ---------------------------------------------------------------------------


def test_local_transaction_begin_commit_and_rollback() -> None:
    server = _server()
    template = "SELECT 1 /* txn */"
    sess = _open(
        server,
        kind=contract.SessionKind.LOCAL,
        template=template,
        operation_id="op-txn",
    )
    server.begin(sess.session_id)
    assert server.session_public_state(sess.session_id)["in_transaction"] is True
    before = server.commit(sess.session_id)
    assert before == 1
    assert server.session_public_state(sess.session_id)["in_transaction"] is False

    server.begin(sess.session_id)
    server.rollback(sess.session_id)
    assert server.session_public_state(sess.session_id)["in_transaction"] is False
    with pytest.raises(contract.SessionError, match="no open transaction"):
        server.rollback(sess.session_id)


def test_stateless_session_rejects_explicit_begin() -> None:
    server = _server()
    sess = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template="SELECT 1 /* stateless */",
        operation_id="op-stateless-begin",
    )
    with pytest.raises(contract.SessionError, match="stateless"):
        server.begin(sess.session_id)


def test_large_fetch_batches_and_completion_releases_handle() -> None:
    server = _server()
    sess = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* large */",
        operation_id="op-large",
    )
    handle = server.start_fetch(sess.session_id, total_rows=2500)
    assert server.session_public_state(sess.session_id)["open_fetch_count"] == 1
    first = server.fetch_next(sess.session_id, handle.fetch_id, batch_size=1000)
    assert first["from"] == 0
    assert first["to"] == 1000
    assert first["done"] is False
    second = server.fetch_next(sess.session_id, handle.fetch_id, batch_size=1000)
    assert second["from"] == 1000
    third = server.fetch_next(sess.session_id, handle.fetch_id, batch_size=1000)
    assert third["done"] is True
    assert third["to"] == 2500
    # Completion auto-releases server state.
    assert server.session_public_state(sess.session_id)["open_fetch_count"] == 0
    assert handle.fetch_id in server.released_fetch_ids()


def test_crashed_client_resource_cleanup() -> None:
    server = _server()
    sess = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* crash */",
        operation_id="op-crash",
    )
    handle = server.start_fetch(sess.session_id, total_rows=10_000)
    cleaned = server.crash_client(sess.session_id)
    assert cleaned["cleaned"] is True
    assert handle.fetch_id in cleaned["released_fetches"]
    assert handle.fetch_id in server.released_fetch_ids()
    with pytest.raises(contract.SessionError):
        server.session_public_state(sess.session_id)

    # In-transaction crash rolls back and releases.
    local = _open(
        server,
        kind=contract.SessionKind.LOCAL,
        template="SELECT 1 /* crash-txn */",
        operation_id="op-crash-txn",
    )
    server.begin(local.session_id)
    handle2 = server.start_fetch(local.session_id, total_rows=100)
    cleaned2 = server.crash_client(local.session_id)
    assert cleaned2["rolled_back_transaction"] is True
    assert handle2.fetch_id in cleaned2["released_fetches"]


# ---------------------------------------------------------------------------
# Known gaps: attached UPDATE/DELETE and ALTER
# ---------------------------------------------------------------------------


def test_known_gaps_registry_has_workarounds_or_hard_gates() -> None:
    assert contract.KNOWN_GAPS
    for gap in contract.KNOWN_GAPS:
        assert gap.gap_id
        assert gap.workaround
        assert gap.disposition in contract.GapDisposition
        payload = gap.to_dict()
        assert payload["disposition"] in {"hard_gate", "workaround"}
        if gap.disposition is contract.GapDisposition.HARD_GATE:
            assert gap.hard_gate_reason


def test_attached_update_delete_is_hard_gated_with_workaround() -> None:
    server = _server()
    template = "UPDATE t SET name = $name WHERE id = $id"
    sess = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template=template,
        operation_id="op-upd",
    )
    with pytest.raises(contract.KnownGapError, match="attached UPDATE/DELETE"):
        server.mutate(
            sess.session_id,
            authorization_template=template,
            parameters={"id": 1, "name": "nope"},
        )

    # Work-around: owner-side rewrite via stateless INSERT path.
    rewrite = "INSERT INTO t VALUES ($id, $name)"
    owner = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=rewrite,
        operation_id="op-rewrite",
    )
    receipt = server.mutate(
        owner.session_id,
        authorization_template=rewrite,
        parameters={"id": 10, "name": "rewritten"},
        rows_to_append=((10, "rewritten"),),
    )
    assert receipt.last_committed_snapshot == server.last_committed_snapshot


def test_attached_alter_is_hard_gated_with_owner_migration_workaround() -> None:
    server = _server()
    template = "ALTER TABLE t ADD COLUMN extra VARCHAR"
    sess = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template=template,
        operation_id="op-alter",
    )
    with pytest.raises(contract.KnownGapError, match="attached ALTER"):
        server.mutate(sess.session_id, authorization_template=template)

    # Work-around evaluation documents owner-gated migration.
    result = contract.evaluate_known_gap(
        "attached_alter",
        session_kind=contract.SessionKind.STATELESS,
        attempt_operation="OWNER_MIGRATION",
    )
    # Gap does not apply to stateless — owner path is free to run migrations.
    assert result["applies"] is False or result.get("gated") is False


def test_multi_statement_remote_hard_gate() -> None:
    assert (
        contract.classify_sql_surface("SELECT 1; SELECT 2")["denied"] is True
    )
    with pytest.raises(contract.KnownGapError, match="multi-statement"):
        contract.evaluate_known_gap(
            "multi_statement_remote",
            session_kind=contract.SessionKind.STATELESS,
            attempt_operation="MULTI_STATEMENT",
        )


def test_server_push_gap_is_workaround_not_gate_for_supervisor() -> None:
    result = contract.evaluate_known_gap(
        "server_push_absent",
        session_kind=contract.SessionKind.LOCAL,
        attempt_operation="SERVER_PUSH",
    )
    assert result["disposition"] == "workaround"
    assert "supervisor" in result["workaround"].lower()


# ---------------------------------------------------------------------------
# DuckLake-over-Quack: concurrent snapshot readers (no shared-session drift)
# ---------------------------------------------------------------------------


def test_concurrent_snapshot_readers_have_no_shared_session_drift() -> None:
    server = _server()

    # Create snapshot 2 via authorized mutation.
    mut_tmpl = "INSERT INTO t VALUES ($id, $name)"
    writer = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=mut_tmpl,
        operation_id="op-writer",
    )
    mut = server.mutate(
        writer.session_id,
        authorization_template=mut_tmpl,
        parameters={"id": 4, "name": "delta"},
        rows_to_append=((4, "delta"),),
    )
    assert mut.last_committed_snapshot == 2
    assert mut.before_snapshot == 1

    r1 = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* r1 */",
        operation_id="op-r1",
        snapshot=1,
    )
    r2 = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* r2 */",
        operation_id="op-r2",
        snapshot=2,
    )

    assert server.session_public_state(r1.session_id)["selected_snapshot"] == 1
    assert server.session_public_state(r2.session_id)["selected_snapshot"] == 2

    rows1 = server.read_snapshot(r1.session_id)
    rows2 = server.read_snapshot(r2.session_id)
    assert len(rows1) == 3
    assert len(rows2) == 4
    assert rows1 != rows2

    # Reader 1 changes its snapshot selection; reader 2 must be untouched.
    server.select_snapshot(r1.session_id, 2)
    st1 = server.session_public_state(r1.session_id)
    st2 = server.session_public_state(r2.session_id)
    assert st1["selected_snapshot"] == 2
    assert st2["selected_snapshot"] == 2  # still 2 — unchanged
    # Re-pin r2 to 1 and prove r1 stays at 2.
    server.select_snapshot(r2.session_id, 1)
    assert server.session_public_state(r1.session_id)["selected_snapshot"] == 2
    assert server.session_public_state(r2.session_id)["selected_snapshot"] == 1
    # Distinct session IDs and independent local_vars.
    assert r1.session_id != r2.session_id
    assert server.session_public_state(r1.session_id)["session_id"] != (
        server.session_public_state(r2.session_id)["session_id"]
    )


def test_authorized_remote_mutation_reports_last_committed_snapshot() -> None:
    server = _server()
    template = "INSERT INTO t VALUES ($id, $name)"
    sess = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=template,
        operation_id="op-mut-receipt",
    )
    before = server.last_committed_snapshot
    receipt = server.mutate(
        sess.session_id,
        authorization_template=template,
        parameters={"id": 7, "name": "seven"},
        rows_to_append=((7, "seven"),),
    )
    assert receipt.before_snapshot == before
    assert receipt.last_committed_snapshot == before + 1
    assert receipt.last_committed_snapshot == server.last_committed_snapshot
    assert receipt.rows_affected == 1
    assert receipt.operation_id == "op-mut-receipt"
    public = receipt.to_dict()
    assert "INSERT INTO" not in public["authorization_template"]
    assert qs.REDACTION_MARKER in public["authorization_template"]


# ---------------------------------------------------------------------------
# Cancellation / lost fetch releases server state
# ---------------------------------------------------------------------------


def test_cancellation_and_lost_fetch_release_server_state() -> None:
    server = _server()
    sess = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* cancel */",
        operation_id="op-cancel",
    )
    h1 = server.start_fetch(sess.session_id, total_rows=50_000)
    h2 = server.start_fetch(sess.session_id, total_rows=50_000)
    assert server.session_public_state(sess.session_id)["open_fetch_count"] == 2

    cancelled = server.cancel_fetch(sess.session_id, h1.fetch_id)
    assert cancelled["released"] is True
    assert cancelled["remaining_open_fetches"] == 1
    assert h1.fetch_id in server.released_fetch_ids()

    lost = server.lost_fetch(sess.session_id, h2.fetch_id)
    assert lost["released"] is True
    assert server.session_public_state(sess.session_id)["open_fetch_count"] == 0
    assert h2.fetch_id in server.released_fetch_ids()

    with pytest.raises(contract.SessionError, match="unknown or released"):
        server.fetch_next(sess.session_id, h1.fetch_id)


# ---------------------------------------------------------------------------
# Prepared parameters separate from authorization template
# ---------------------------------------------------------------------------


def test_prepared_parameters_remain_separate_from_authorization_template() -> None:
    server = _server()
    template = "INSERT INTO t VALUES ($id, $name)"
    sess = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=template,
        operation_id="op-params",
    )
    params = {"id": 42, "name": "answer"}
    receipt = server.mutate(
        sess.session_id,
        authorization_template=template,
        parameters=params,
        rows_to_append=((42, "answer"),),
    )
    rendered = contract._render_authorization_template(template, params)
    assert rendered != template
    assert "$id" not in rendered
    assert "42" in rendered

    template_digest = hashlib.sha256(template.encode("utf-8")).hexdigest()
    assert receipt.rendered_sql_digest != template_digest
    assert receipt.parameters_digest == hashlib.sha256(
        json.dumps(params, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    # Authorization identity is the template, never the rendered SQL.
    with pytest.raises(qs.AuthorizationError):
        server.authorize_only(sess.session_id, rendered)
    assert server.authorize_only(sess.session_id, template) is True


# ---------------------------------------------------------------------------
# Internal-surface denial
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM ducklake_metadata",
        "SELECT ducklake_file_key('blob')",
        "SELECT ducklake_encryption_key FROM secrets",
        "SELECT duckdb_encryption_key()",
        "SHOW TABLES",
        "SHOW DATABASES",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM duckdb_schemas()",
        "SELECT * FROM duckdb_databases()",
        "SELECT * FROM duckdb_extensions()",
        "SELECT * FROM duckdb_settings()",
        "SELECT * FROM duckdb_secrets()",
        "SET threads=4",
        "RESET threads",
        "PRAGMA show_tables",
        "COPY t TO 'out.parquet'",
        "SELECT * FROM read_parquet('x.parquet')",
        "SELECT * FROM read_csv('x.csv')",
        "SELECT * FROM read_json('x.json')",
        "SELECT * FROM read_blob('x')",
        "SELECT * FROM read_text('x')",
        "SELECT * FROM httpfs_list('s3://bucket')",
        "INSTALL httpfs",
        "LOAD quack",
        "ATTACH 'file.db' AS other",
        "DETACH other",
        "CREATE SECRET s (TYPE S3)",
        "SELECT * FROM t FROM 'evil.parquet'",
    ],
)
def test_internal_and_network_surfaces_remain_unreachable(sql: str) -> None:
    classification = contract.classify_sql_surface(sql)
    # Path-scan edge case may only match for FROM ' patterns; others must deny.
    if "FROM 'evil" in sql:
        # Our classifier looks for FROM ' after uppercasing.
        assert classification["denied"] is True
    else:
        assert classification["denied"] is True, sql
        assert classification["matched"]

    server = _server()
    sess = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template="SELECT 1 /* deny-base */",
        operation_id=f"op-deny-{hashlib.sha256(sql.encode()).hexdigest()[:8]}",
    )
    with pytest.raises(
        (contract.SurfaceDeniedError, contract.KnownGapError, qs.AuthorizationError)
    ):
        server.authorize_only(sess.session_id, sql)


def test_denied_internal_surfaces_constant_covers_required_families() -> None:
    joined = " ".join(s.lower() for s in contract.DENIED_INTERNAL_SURFACES)
    for required in (
        "ducklake_metadata",
        "ducklake_file_key",
        "show ",
        "duckdb_",
        "set ",
        "reset ",
        "pragma ",
        "copy ",
        "read_csv",
        "read_parquet",
        "read_json",
        "httpfs",
    ):
        assert required in joined


# ---------------------------------------------------------------------------
# Extension pinning + upgrade refusal vs DQK-084
# ---------------------------------------------------------------------------


def test_default_profile_matches_exact_dqk084_capability_profile() -> None:
    profile = contract.DEFAULT_COMPATIBILITY_PROFILE
    contract.assert_extension_pins_match_dqk084(profile)
    assert profile.duckdb_version == lake_caps.REQUIRED_DUCKDB_VERSION_TEXT
    assert profile.quack_extension_build == lake_caps.PINNED_QUACK_EXTENSION_BUILD
    assert profile.ducklake_extension_build == lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD
    assert profile.httpfs_extension_build == lake_caps.PINNED_HTTPFS_EXTENSION_BUILD
    assert tuple(profile.load_order) == tuple(lake_caps.EXPLICIT_LOAD_ORDER)
    assert profile.automatic_install is False
    assert profile.automatic_load is False
    assert profile.automatic_migration is False
    assert profile.ducklake_spec_version == lake_caps.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION
    assert profile.to_dict()["capability_profile_ref"] == "DQK-084"


def test_extension_pin_mismatch_vs_dqk084_fails() -> None:
    bad = contract.CompatibilityProfile(quack_extension_build="quack@9.9.9+core")
    with pytest.raises(contract.ProtocolMismatchError, match="Quack build mismatch"):
        contract.assert_extension_pins_match_dqk084(bad)
    bad_auto = contract.CompatibilityProfile(automatic_install=True)
    with pytest.raises(contract.ProtocolMismatchError, match="automatic"):
        contract.assert_extension_pins_match_dqk084(bad_auto)


def test_server_client_extension_mismatch_fails_before_mutation() -> None:
    server = _server()
    bad_client = contract.CompatibilityProfile(duckdb_version="1.4.1")
    template = "INSERT INTO t VALUES (1)"
    cap = server.mint_capability(
        operation_id="op-mismatch",
        authorization_template=template,
    )
    with pytest.raises(contract.ProtocolMismatchError, match="before mutation"):
        server.open_session(
            session_kind=contract.SessionKind.STATELESS,
            capability_secret=cap.secret,
            client_profile=bad_client,
        )
    # Catalog must remain at snapshot 1 — no mutation occurred.
    assert server.last_committed_snapshot == 1
    assert server.mutation_receipts() == ()

    # Protocol mismatch also fails before mutation when sessions already open.
    good = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=template,
        operation_id="op-good",
    )
    with pytest.raises(contract.ProtocolMismatchError):
        server.mutate(
            good.session_id,
            authorization_template=template,
            client_profile=contract.CompatibilityProfile(
                protocol_version=99,
            ),
        )
    assert server.last_committed_snapshot == 1


def test_protocol_version_must_be_supported() -> None:
    server_profile = contract.DEFAULT_COMPATIBILITY_PROFILE
    client = contract.CompatibilityProfile(protocol_version=99)
    with pytest.raises(contract.ProtocolMismatchError, match="protocol"):
        contract.assert_profile_compatible_before_mutation(
            server=server_profile,
            client=client,
        )


# ---------------------------------------------------------------------------
# Quack beta + DuckDB 2.0 receipts
# ---------------------------------------------------------------------------


def test_quack_beta_use_requires_compatibility_receipt() -> None:
    with pytest.raises(contract.UpgradeRefusedError, match="compatibility/risk receipt"):
        contract.refuse_upgrade(target_duckdb_version="1.5.5")

    receipt = contract.build_quack_beta_compatibility_receipt()
    contract.require_compatibility_receipt(receipt)
    assert receipt["schema"] == contract.COMPATIBILITY_RECEIPT_SCHEMA
    assert receipt["task_id"] == "DQK-050"
    assert receipt["quack_beta"] is True
    assert receipt["risk_accepted"] is True
    assert receipt["feature_gate_enabled"] is True
    assert receipt["local_fallback_enabled"] is True
    assert receipt["capability_profile_ref"] == "DQK-084"
    assert receipt["pre_gate"] == "DQK-104"
    assert control_caps.QUACK_BETA is True
    assert "not production-ready until DuckDB 2.0" in receipt["quack_status_reason"]

    # With receipt, beta use on 1.5.5 is admitted.
    contract.refuse_upgrade(
        target_duckdb_version="1.5.5",
        compatibility_receipt=receipt,
    )


def test_duckdb_20_adoption_requires_requalification_receipt() -> None:
    compat = contract.build_quack_beta_compatibility_receipt()
    with pytest.raises(contract.UpgradeRefusedError, match="requalification"):
        contract.refuse_upgrade(
            target_duckdb_version="2.0.0",
            compatibility_receipt=compat,
        )

    requal = contract.build_duckdb_20_requalification_receipt(
        compatibility_receipt=compat,
    )
    contract.require_requalification_receipt(requal)
    assert requal["schema"] == contract.REQUALIFICATION_RECEIPT_SCHEMA
    assert requal["target_duckdb_version"] == "2.0.0"
    assert requal["requires_full_contract_rerun"] is True
    assert requal["bound_compatibility_receipt_id"] == compat["receipt_id"]

    contract.refuse_upgrade(
        target_duckdb_version="2.0.0",
        requalification_receipt=requal,
    )


def test_tampered_compatibility_receipt_fails_closed() -> None:
    receipt = contract.build_quack_beta_compatibility_receipt()
    tampered = dict(receipt)
    tampered["risk_accepted"] = False
    with pytest.raises(contract.CompatibilityError):
        contract.require_compatibility_receipt(tampered)

    tampered2 = dict(receipt)
    tampered2["acceptor_identity"] = "attacker"
    with pytest.raises(contract.CompatibilityError, match="signature"):
        contract.require_compatibility_receipt(tampered2)


def test_receipt_builders_reject_unsafe_defaults() -> None:
    with pytest.raises(contract.CompatibilityError, match="risk"):
        contract.build_quack_beta_compatibility_receipt(risk_accepted=False)
    with pytest.raises(contract.CompatibilityError, match="feature gate"):
        contract.build_quack_beta_compatibility_receipt(feature_gate_enabled=False)
    with pytest.raises(contract.CompatibilityError, match="fallback"):
        contract.build_quack_beta_compatibility_receipt(local_fallback_enabled=False)
    compat = contract.build_quack_beta_compatibility_receipt()
    with pytest.raises(contract.CompatibilityError, match=">= 2.0.0"):
        contract.build_duckdb_20_requalification_receipt(
            target_duckdb_version="1.9.0",
            compatibility_receipt=compat,
        )


# ---------------------------------------------------------------------------
# Pre-DQK-104 gate: DuckLake-over-Quack slice must pass as a unit
# ---------------------------------------------------------------------------


def test_ducklake_over_quack_slice_passes_before_dqk104() -> None:
    """Aggregate slice required before DQK-104 catalog-owner production path."""

    server = _server()
    assert contract.PRE_DQK_104_GATE == "DQK-104"

    # Authentication
    mut_tmpl = "INSERT INTO t VALUES ($id, $name)"
    writer = _open(
        server,
        kind=contract.SessionKind.STATELESS,
        template=mut_tmpl,
        operation_id="op-pre-104-mut",
    )

    # Mutation + last committed snapshot
    receipt = server.mutate(
        writer.session_id,
        authorization_template=mut_tmpl,
        parameters={"id": 5, "name": "eps"},
        rows_to_append=((5, "eps"),),
    )
    assert receipt.last_committed_snapshot == 2

    # Snapshot reads without drift
    a = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* a */",
        operation_id="op-pre-104-a",
        snapshot=1,
    )
    b = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* b */",
        operation_id="op-pre-104-b",
        snapshot=2,
    )
    assert len(server.read_snapshot(a.session_id)) == 3
    assert len(server.read_snapshot(b.session_id)) == 4
    server.select_snapshot(a.session_id, 1)
    assert server.session_public_state(b.session_id)["selected_snapshot"] == 2

    # Parameterization separate from template
    rendered = contract._render_authorization_template(
        mut_tmpl, {"id": 5, "name": "eps"}
    )
    assert rendered != mut_tmpl
    with pytest.raises(qs.AuthorizationError):
        server.authorize_only(writer.session_id, rendered)

    # Cancellation releases state
    fetch_sess = _open(
        server,
        kind=contract.SessionKind.ATTACHED,
        template="SELECT * FROM t /* pre-fetch */",
        operation_id="op-pre-104-fetch",
    )
    handle = server.start_fetch(fetch_sess.session_id, total_rows=9000)
    assert server.cancel_fetch(fetch_sess.session_id, handle.fetch_id)["released"]

    # Internal-surface denial
    with pytest.raises(contract.SurfaceDeniedError):
        server.authorize_only(writer.session_id, "SELECT * FROM ducklake_metadata")
    with pytest.raises(contract.SurfaceDeniedError):
        server.authorize_only(writer.session_id, "SHOW TABLES")
    with pytest.raises(contract.SurfaceDeniedError):
        server.authorize_only(writer.session_id, "SET threads=1")

    # Compatibility receipt binds pre-gate
    receipt_doc = contract.build_quack_beta_compatibility_receipt()
    assert receipt_doc["pre_gate"] == "DQK-104"
    contract.require_compatibility_receipt(receipt_doc)


# ---------------------------------------------------------------------------
# Full suite runner + CLI smoke
# ---------------------------------------------------------------------------


def test_run_contract_suite_passes() -> None:
    report = contract.run_contract_suite()
    assert report["ok"] is True
    assert report["failed"] == 0
    assert report["task_id"] == "DQK-050"
    assert report["capability_profile_ref"] == "DQK-084"
    assert report["passed"] >= 9
    names = {r["name"] for r in report["results"]}
    assert "concurrent_snapshot_readers" in names
    assert "internal_surface_denial" in names
    assert "compatibility_and_requalification_receipts" in names


def test_main_cli_json_and_receipt(capsys: pytest.CaptureFixture[str]) -> None:
    rc = contract.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True

    rc2 = contract.main(["--emit-receipt", "--emit-requalification"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    envelope = json.loads(out2)
    contract.require_compatibility_receipt(envelope["compatibility_receipt"])
    contract.require_requalification_receipt(envelope["requalification_receipt"])


def test_control_plane_quack_beta_pins_align() -> None:
    """Cross-check DQK-002 / DQK-084 pins used by the contract."""

    assert control_caps.REQUIRED_DUCKDB_VERSION_TEXT == "1.5.5"
    assert control_caps.QUACK_BETA is True
    assert control_caps.QUACK_PRODUCTION_READY_FROM_DUCKDB == (2, 0, 0)
    assert lake_caps.REQUIRED_DUCKDB_VERSION_TEXT == "1.5.5"
    assert lake_caps.PINNED_QUACK_EXTENSION_BUILD == control_caps.PINNED_QUACK_EXTENSION_BUILD
    assert contract.DEFAULT_COMPATIBILITY_PROFILE.quack_beta is True
