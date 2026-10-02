"""DuckDB + Quack + DuckLake meta-index over supervisor catalogs.

Links filesystem/mtime, AST, BM25, knowledge-graph, vector, proof-cache,
proof-certificate, world-model, capsule, and taskboard catalogs by content
identity. Extra-gate exclusive ``control.duckdb`` is registered as a locator
only and is never attached. DuckLake history is observational. Records inform
event-driven orchestration and capsule composition; they never admit
completion.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "ipfs_accelerate_py/supervisor-meta-index@1"
INTERFACE = "SupervisorMetaIndex@1"
ENV_DUCKDB = "IPFS_ACCELERATE_META_INDEX_DUCKDB"
ENV_DUCKLAKE = "IPFS_ACCELERATE_META_INDEX_DUCKLAKE"

CATALOG_KINDS = frozenset(
    {
        "filesystem_mtime",
        "ast",
        "bm25",
        "knowledge_graph",
        "vector",
        "proof_cache",
        "proof_certificate",
        "world_model",
        "taskboard",
        "capsule",
        "metadata",
    }
)
SUBJECT_KINDS = frozenset(
    {
        "path",
        "content_cid",
        "tree_id",
        "task_id",
        "obligation_ref",
        "capsule_cid",
        "record_cid",
        "key_id",
        "receipt_id",
    }
)
DDL = """
CREATE TABLE IF NOT EXISTS catalogs (
    catalog_id VARCHAR PRIMARY KEY,
    catalog_cid VARCHAR NOT NULL UNIQUE,
    kind VARCHAR NOT NULL,
    locator_ref VARCHAR NOT NULL,
    exclusive_owner VARCHAR NOT NULL,
    attach_permitted BOOLEAN NOT NULL,
    repository_id VARCHAR NOT NULL,
    tree_id VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL,
    completion_authority BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS identity_links (
    link_id VARCHAR PRIMARY KEY,
    link_cid VARCHAR NOT NULL UNIQUE,
    subject_kind VARCHAR NOT NULL,
    subject_ref VARCHAR NOT NULL,
    catalog_id VARCHAR NOT NULL,
    record_kind VARCHAR NOT NULL,
    record_ref VARCHAR NOT NULL,
    freshness_mtime_ns BIGINT,
    recorded_at VARCHAR NOT NULL,
    completion_authority BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS identity_links_subject_idx
    ON identity_links(subject_kind, subject_ref, catalog_id);
CREATE TABLE IF NOT EXISTS capsule_bindings (
    binding_id VARCHAR PRIMARY KEY,
    capsule_cid VARCHAR NOT NULL,
    catalog_id VARCHAR NOT NULL,
    subject_kind VARCHAR NOT NULL,
    subject_ref VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL,
    completion_authority BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS capsule_bindings_capsule_idx
    ON capsule_bindings(capsule_cid, catalog_id);
"""


class SupervisorMetaIndexError(ValueError):
    """Closed meta-index contract violation."""


def _cid(payload: Mapping[str, Any]) -> str:
    from ipfs_accelerate_py.mcp_server.mcplusplus.kubo_cid import cid_for_bytes

    body = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return cid_for_bytes(body.encode("utf-8"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _refuse_extra_gate_control_plane(path: Path) -> None:
    if path.resolve().name == "control.duckdb":
        raise SupervisorMetaIndexError(
            "meta-index refuses extra-gate exclusive control.duckdb"
        )


def _connect(path: Path):
    import duckdb

    _refuse_extra_gate_control_plane(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path), config={"threads": 1})
    connection.execute(DDL)
    return connection


def _attach_permitted(locator_ref: str, exclusive_owner: str) -> bool:
    name = Path(str(locator_ref or "")).name
    if name == "control.duckdb":
        return False
    if exclusive_owner:
        return False
    return bool(locator_ref)


@dataclass
class SupervisorMetaIndex:
    duckdb_path: Path
    ducklake_root: Path | None = None

    @classmethod
    def from_env(cls) -> "SupervisorMetaIndex | None":
        configured = str(os.environ.get(ENV_DUCKDB) or "").strip()
        if not configured:
            return None
        lake = str(os.environ.get(ENV_DUCKLAKE) or "").strip()
        return cls(Path(configured), Path(lake) if lake else None)

    def register_catalog(
        self,
        *,
        kind: str,
        locator_ref: str,
        exclusive_owner: str = "",
        repository_id: str = "",
        tree_id: str = "",
        project: bool = True,
    ) -> dict[str, Any]:
        if kind not in CATALOG_KINDS:
            raise SupervisorMetaIndexError(f"unknown catalog kind {kind}")
        attach = _attach_permitted(locator_ref, exclusive_owner)
        recorded_at = _now()
        catalog_cid = _cid(
            {
                "kind": kind,
                "locator_ref": locator_ref,
                "exclusive_owner": exclusive_owner,
                "repository_id": repository_id,
                "tree_id": tree_id,
            }
        )
        catalog_id = f"catalog:{kind}:{catalog_cid}"
        connection = _connect(self.duckdb_path)
        try:
            connection.execute(
                """
                INSERT INTO catalogs (
                    catalog_id, catalog_cid, kind, locator_ref, exclusive_owner,
                    attach_permitted, repository_id, tree_id, recorded_at,
                    completion_authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE)
                ON CONFLICT (catalog_cid) DO UPDATE SET
                    recorded_at=excluded.recorded_at
                """,
                [
                    catalog_id,
                    catalog_cid,
                    kind,
                    locator_ref,
                    exclusive_owner,
                    attach,
                    repository_id,
                    tree_id,
                    recorded_at,
                ],
            )
        finally:
            connection.close()
        if project:
            self.project_ducklake()
        return {
            "schema": SCHEMA,
            "interface": INTERFACE,
            "catalog_id": catalog_id,
            "catalog_cid": catalog_cid,
            "kind": kind,
            "locator_ref": locator_ref,
            "repository_id": repository_id,
            "exclusive_owner": exclusive_owner,
            "attach_permitted": attach,
            "completion_authority": False,
        }

    def link_identity(
        self,
        *,
        subject_kind: str,
        subject_ref: str,
        catalog_id: str,
        record_kind: str,
        record_ref: str,
        freshness_mtime_ns: int | None = None,
        capsule_cid: str = "",
        project: bool = True,
    ) -> dict[str, Any]:
        return self.link_identities([{
            "subject_kind": subject_kind, "subject_ref": subject_ref,
            "catalog_id": catalog_id, "record_kind": record_kind, "record_ref": record_ref,
            "freshness_mtime_ns": freshness_mtime_ns, "capsule_cid": capsule_cid,
        }], project=project)[0]

    def link_identities(
        self, records: Sequence[Mapping[str, Any]], *, project: bool = True,
    ) -> list[dict[str, Any]]:
        """Persist a bounded batch atomically, then project DuckLake once.

        Link identities and capsule bindings match ``link_identity`` exactly.
        A batch avoids opening the catalog for every symbol during hydration.
        """
        if not isinstance(records, (list, tuple)) or not 1 <= len(records) <= 10_000:
            raise SupervisorMetaIndexError("identity batch requires 1 to 10000 records")
        recorded_at = _now()
        identities, bindings, results = [], [], []
        required = {"subject_kind", "subject_ref", "catalog_id", "record_kind", "record_ref"}
        for record in records:
            if (not isinstance(record, Mapping) or not required <= set(record)
                    or set(record) - required - {"freshness_mtime_ns", "capsule_cid"}):
                raise SupervisorMetaIndexError("invalid identity batch record")
            subject_kind, subject_ref = record["subject_kind"], record["subject_ref"]
            catalog_id, record_ref = record["catalog_id"], record["record_ref"]
            if subject_kind not in SUBJECT_KINDS:
                raise SupervisorMetaIndexError(f"unknown subject kind {subject_kind}")
            if not subject_ref or not catalog_id or not record_ref:
                raise SupervisorMetaIndexError("subject, catalog, and record refs are required")
            link_cid = _cid({key: record[key] for key in required})
            link_id = f"link:{link_cid}"
            identities.append([
                link_id, link_cid, subject_kind, subject_ref, catalog_id,
                record["record_kind"], record_ref, record.get("freshness_mtime_ns"), recorded_at,
            ])
            if capsule_cid := record.get("capsule_cid"):
                binding_cid = _cid({"capsule_cid": capsule_cid, "catalog_id": catalog_id,
                                    "subject_ref": subject_ref})
                bindings.append([f"binding:{binding_cid}", capsule_cid, catalog_id,
                                 subject_kind, subject_ref, recorded_at])
            results.append({"schema": SCHEMA, "link_id": link_id, "link_cid": link_cid,
                            "completion_authority": False})
        connection = _connect(self.duckdb_path)
        try:
            connection.execute("BEGIN TRANSACTION")
            connection.executemany(
                """
                INSERT INTO identity_links (
                    link_id, link_cid, subject_kind, subject_ref, catalog_id,
                    record_kind, record_ref, freshness_mtime_ns, recorded_at,
                    completion_authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE)
                ON CONFLICT (link_cid) DO UPDATE SET
                    freshness_mtime_ns=excluded.freshness_mtime_ns,
                    recorded_at=excluded.recorded_at
                """,
                identities,
            )
            if bindings:
                connection.executemany(
                    """
                    INSERT INTO capsule_bindings (
                        binding_id, capsule_cid, catalog_id, subject_kind,
                        subject_ref, recorded_at, completion_authority
                    ) VALUES (?, ?, ?, ?, ?, ?, FALSE)
                    ON CONFLICT (binding_id) DO UPDATE SET
                        recorded_at=excluded.recorded_at
                    """,
                    bindings,
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        if project:
            self.project_ducklake()
        return results

    def bind_supervisor_catalogs(
        self,
        *,
        tree_id: str = "",
        locators: Mapping[str, str] | None = None,
        taskboards: Sequence[Mapping[str, str]] | None = None,
    ) -> dict[str, Any]:
        env_locators = {
            "ast": str(os.environ.get("IPFS_ACCELERATE_AST_INDEX_DUCKDB") or "ast"),
            "bm25": str(os.environ.get("IPFS_ACCELERATE_BM25_DUCKDB") or "bm25"),
            "vector": str(os.environ.get("IPFS_ACCELERATE_VECTOR_DUCKDB") or "vector"),
            "knowledge_graph": str(
                os.environ.get("IPFS_ACCELERATE_KNOWLEDGE_GRAPH_DUCKDB") or "knowledge_graph"
            ),
            "world_model": str(os.environ.get("IPFS_ACCELERATE_PROGRAM_WORLD_DUCKDB") or "world_model"),
            "proof_cache": str(
                os.environ.get("IPFS_ACCELERATE_PROOF_CERTIFICATE_DUCKDB") or "proof_cache"
            ),
            "proof_certificate": str(
                os.environ.get("IPFS_ACCELERATE_PROOF_CERTIFICATE_DUCKDB") or "proof_certificate"
            ),
            "filesystem_mtime": str(os.environ.get("IPFS_ACCELERATE_META_INDEX_MTIME") or "filesystem"),
            "capsule": str(os.environ.get("IPFS_ACCELERATE_CAPSULE_INDEX") or "capsule"),
            "metadata": str(os.environ.get("IPFS_ACCELERATE_METADATA_INDEX") or "metadata"),
        }
        if locators:
            env_locators.update({str(key): str(value) for key, value in locators.items() if value})
        catalogs = []
        for kind, locator in env_locators.items():
            if not locator:
                continue
            catalogs.append(
                self.register_catalog(
                    kind=kind,
                    locator_ref=locator,
                    tree_id=tree_id,
                    project=False,
                )
            )
        boards = list(taskboards or ())
        if not boards:
            boards = [
                {
                    "board_id": "sawm",
                    "exclusive_owner": "ipfs-taskboard-sawm-supervisor.service",
                    "locator_ref": "quack://sawm",
                },
                {
                    "board_id": "doep",
                    "exclusive_owner": "agent-supervisor-doep-v1.service",
                    "locator_ref": "quack://doep",
                },
                {
                    "board_id": "spar",
                    "exclusive_owner": "ipfs-taskboard-spar-supervisor.service",
                    "locator_ref": "quack://spar",
                },
                {
                    "board_id": "pctdd",
                    "exclusive_owner": "pctdd-g9-quack-owner.service",
                    "locator_ref": "quack://pctdd",
                },
                {
                    "board_id": "aseh",
                    "exclusive_owner": "ipfs-taskboard-aseh-supervisor.service",
                    "locator_ref": "quack://aseh",
                },
            ]
        for board in boards:
            catalogs.append(
                self.register_catalog(
                    kind="taskboard",
                    locator_ref=str(board.get("locator_ref") or f"quack://{board.get('board_id')}"),
                    exclusive_owner=str(board.get("exclusive_owner") or ""),
                    repository_id=str(board.get("board_id") or ""),
                    tree_id=tree_id,
                    project=False,
                )
            )
        projection = self.project_ducklake()
        return {
            "schema": SCHEMA,
            "interface": INTERFACE,
            "catalogs": catalogs,
            "n": len(catalogs),
            "ducklake": projection,
            "completion_authority": False,
            "extra_gate_attached": False,
            "event_driven_qualified": True,
        }

    def link_orchestration_catalogs(
        self,
        catalogs: Sequence[Mapping[str, Any]],
        *,
        subject_kind: str,
        subject_ref: str,
        tree_id: str = "",
        capsule_cid: str = "",
    ) -> list[dict[str, Any]]:
        """Join one subject to every bound catalog. Task boards stay unattached.

        Record refs are catalog kinds or board ids. Locator paths are not stored.
        """

        subjects: list[tuple[str, str]] = []
        if subject_kind in SUBJECT_KINDS and subject_ref:
            subjects.append((subject_kind, subject_ref))
        if tree_id and ("tree_id", tree_id) not in subjects:
            subjects.append(("tree_id", tree_id))
        if not subjects:
            return []
        recorded_at = _now()
        links: list[dict[str, Any]] = []
        connection = _connect(self.duckdb_path)
        try:
            for catalog in catalogs:
                catalog_kind = str(catalog.get("kind") or "")
                catalog_id = str(catalog.get("catalog_id") or "")
                if catalog_kind not in CATALOG_KINDS or not catalog_id:
                    continue
                if catalog_kind == "taskboard":
                    record_ref = str(catalog.get("repository_id") or "").strip()
                    locator = str(catalog.get("locator_ref") or "")
                    if not record_ref and locator.startswith("quack://"):
                        record_ref = locator[len("quack://") :].strip()
                    record_ref = record_ref or "taskboard"
                    bound_capsule = ""
                else:
                    record_ref = catalog_kind
                    bound_capsule = capsule_cid
                for kind, ref in subjects:
                    link_cid = _cid(
                        {
                            "subject_kind": kind,
                            "subject_ref": ref,
                            "catalog_id": catalog_id,
                            "record_kind": catalog_kind,
                            "record_ref": record_ref,
                        }
                    )
                    connection.execute(
                        """
                        INSERT INTO identity_links (
                            link_id, link_cid, subject_kind, subject_ref, catalog_id,
                            record_kind, record_ref, freshness_mtime_ns, recorded_at,
                            completion_authority
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, FALSE)
                        ON CONFLICT (link_cid) DO UPDATE SET
                            recorded_at=excluded.recorded_at
                        """,
                        [
                            f"link:{link_cid}",
                            link_cid,
                            kind,
                            ref,
                            catalog_id,
                            catalog_kind,
                            record_ref,
                            recorded_at,
                        ],
                    )
                    if bound_capsule:
                        binding_cid = _cid(
                            {
                                "capsule_cid": bound_capsule,
                                "catalog_id": catalog_id,
                                "subject_ref": ref,
                            }
                        )
                        connection.execute(
                            """
                            INSERT INTO capsule_bindings (
                                binding_id, capsule_cid, catalog_id, subject_kind,
                                subject_ref, recorded_at, completion_authority
                            ) VALUES (?, ?, ?, ?, ?, ?, FALSE)
                            ON CONFLICT (binding_id) DO UPDATE SET
                                recorded_at=excluded.recorded_at
                            """,
                            [
                                f"binding:{binding_cid}",
                                bound_capsule,
                                catalog_id,
                                kind,
                                ref,
                                recorded_at,
                            ],
                        )
                    links.append(
                        {
                            "subject_kind": kind,
                            "subject_ref": ref,
                            "catalog_id": catalog_id,
                            "record_kind": catalog_kind,
                            "record_ref": record_ref,
                            "completion_authority": False,
                        }
                    )
        finally:
            connection.close()
        return links

    def observe_path(
        self,
        path: str,
        *,
        mtime_ns: int | None = None,
        content_cid: str = "",
        tree_id: str = "",
        capsule_cid: str = "",
        extra_kinds: Sequence[str] = (),
    ) -> dict[str, Any]:
        filesystem = self.register_catalog(
            kind="filesystem_mtime",
            locator_ref="filesystem",
            tree_id=tree_id,
            project=False,
        )
        links = [
            self.link_identity(
                subject_kind="path",
                subject_ref=path,
                catalog_id=str(filesystem.get("catalog_id") or ""),
                record_kind="mtime",
                record_ref=content_cid or path,
                freshness_mtime_ns=mtime_ns,
                capsule_cid=capsule_cid,
                project=False,
            )
        ]
        if content_cid:
            links.append(
                self.link_identity(
                    subject_kind="content_cid",
                    subject_ref=content_cid,
                    catalog_id=str(filesystem.get("catalog_id") or ""),
                    record_kind="mtime",
                    record_ref=path,
                    freshness_mtime_ns=mtime_ns,
                    capsule_cid=capsule_cid,
                    project=False,
                )
            )
        for kind in extra_kinds:
            if kind not in CATALOG_KINDS or kind == "filesystem_mtime":
                continue
            catalog = self.register_catalog(
                kind=kind,
                locator_ref=kind,
                tree_id=tree_id,
                project=False,
            )
            links.append(
                self.link_identity(
                    subject_kind="path",
                    subject_ref=path,
                    catalog_id=str(catalog.get("catalog_id") or ""),
                    record_kind=kind,
                    record_ref=content_cid or path,
                    freshness_mtime_ns=mtime_ns,
                    capsule_cid=capsule_cid,
                    project=False,
                )
            )
        projection = self.project_ducklake()
        return {
            "schema": SCHEMA,
            "path": path,
            "links": links,
            "n": len(links),
            "ducklake": projection,
            "completion_authority": False,
            "event_driven_qualified": True,
        }

    def compose_semantic_work(
        self,
        *,
        subject_kind: str,
        subject_ref: str,
        tree_id: str = "",
    ) -> dict[str, Any]:
        composed = self.compose_for_subject(subject_kind=subject_kind, subject_ref=subject_ref)
        view = self.orchestration_view(tree_id=tree_id)
        kinds = sorted({item["catalog_kind"] for item in composed.get("linked") or []})
        return {
            "schema": SCHEMA,
            "interface": INTERFACE,
            "subject_kind": subject_kind,
            "subject_ref": subject_ref,
            "linked": composed.get("linked") or [],
            "catalogs": view.get("catalogs") or [],
            "kinds": kinds,
            "n": int(composed.get("n") or 0),
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
            "extra_gate_attached": False,
            "capsule_composition": True,
            "formal_surfaces": [
                name
                for name in sorted(CATALOG_KINDS)
                if name in kinds or name in (view.get("kinds") or [])
            ],
        }

    def orchestrate_semantic_work(
        self,
        *,
        subject_kind: str = "tree_id",
        subject_ref: str = "",
        tree_id: str = "",
        path: str = "",
        mtime_ns: int | None = None,
        content_cid: str = "",
        capsule_cid: str = "",
    ) -> dict[str, Any]:
        bound = self.bind_supervisor_catalogs(tree_id=tree_id or subject_ref)
        observed = None
        self.link_orchestration_catalogs(
            bound.get("catalogs") or [],
            subject_kind=subject_kind,
            subject_ref=subject_ref or path or tree_id,
            tree_id=tree_id or subject_ref,
            capsule_cid=capsule_cid,
        )
        if path:
            observed = self.observe_path(
                path,
                mtime_ns=mtime_ns,
                content_cid=content_cid,
                tree_id=tree_id or subject_ref,
                capsule_cid=capsule_cid,
                extra_kinds=tuple(
                    kind
                    for kind in sorted(CATALOG_KINDS)
                    if kind not in {"filesystem_mtime", "taskboard"}
                ),
            )
        composed = self.compose_semantic_work(
            subject_kind=subject_kind,
            subject_ref=subject_ref or path or tree_id,
            tree_id=tree_id or subject_ref,
        )
        required = set(CATALOG_KINDS)
        present = {str(item.get("kind") or "") for item in (bound.get("catalogs") or [])}
        present.update(composed.get("kinds") or [])
        present.discard("")
        return {
            **composed,
            "bound": bound,
            "observed": observed,
            "required_kinds": sorted(required),
            "missing_kinds": sorted(required - present),
            "catalogs_linked": required <= present,
            "ducklake": self.project_ducklake(),
        }

    def compose_for_subject(
        self,
        *,
        subject_kind: str,
        subject_ref: str,
        limit: int = 64,
    ) -> dict[str, Any]:
        if subject_kind not in SUBJECT_KINDS:
            raise SupervisorMetaIndexError(f"unknown subject kind {subject_kind}")
        if limit < 1 or limit > 256:
            raise SupervisorMetaIndexError("compose limit must be 1..256")
        connection = _connect(self.duckdb_path)
        try:
            rows = connection.execute(
                """
                SELECT l.subject_kind, l.subject_ref, l.record_kind, l.record_ref,
                       l.freshness_mtime_ns, c.kind, c.catalog_id, c.locator_ref,
                       c.attach_permitted, c.exclusive_owner, l.recorded_at
                FROM identity_links l
                JOIN catalogs c ON c.catalog_id = l.catalog_id
                WHERE l.subject_kind = ? AND l.subject_ref = ?
                ORDER BY l.recorded_at DESC
                LIMIT ?
                """,
                [subject_kind, subject_ref, int(limit)],
            ).fetchall()
            bound_rows = []
            if subject_kind == "capsule_cid":
                bound_rows = connection.execute(
                    """
                    SELECT l.subject_kind, l.subject_ref, l.record_kind, l.record_ref,
                           l.freshness_mtime_ns, c.kind, c.catalog_id, c.locator_ref,
                           c.attach_permitted, c.exclusive_owner, l.recorded_at
                    FROM capsule_bindings b
                    JOIN identity_links l
                      ON l.catalog_id = b.catalog_id
                     AND l.subject_kind = b.subject_kind
                     AND l.subject_ref = b.subject_ref
                    JOIN catalogs c ON c.catalog_id = l.catalog_id
                    WHERE b.capsule_cid = ?
                    ORDER BY l.recorded_at DESC
                    LIMIT ?
                    """,
                    [subject_ref, int(limit)],
                ).fetchall()
        finally:
            connection.close()
        linked = []
        seen: set[tuple[Any, ...]] = set()
        for row in list(rows) + list(bound_rows):
            key = (row[0], row[1], row[2], row[3], row[6])
            if key in seen:
                continue
            seen.add(key)
            linked.append(
                {
                    "subject_kind": row[0],
                    "subject_ref": row[1],
                    "record_kind": row[2],
                    "record_ref": row[3],
                    "freshness_mtime_ns": row[4],
                    "catalog_kind": row[5],
                    "catalog_id": row[6],
                    "locator_ref": row[7],
                    "attach_permitted": bool(row[8]),
                    "exclusive_owner": row[9],
                    "recorded_at": row[10],
                }
            )
            if len(linked) >= int(limit):
                break
        return {
            "schema": SCHEMA,
            "interface": INTERFACE,
            "subject_kind": subject_kind,
            "subject_ref": subject_ref,
            "linked": linked,
            "n": len(linked),
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
        }

    def orchestration_view(self, *, tree_id: str = "", limit: int = 64) -> dict[str, Any]:
        if limit < 1 or limit > 256:
            raise SupervisorMetaIndexError("orchestration limit must be 1..256")
        connection = _connect(self.duckdb_path)
        try:
            if tree_id:
                rows = connection.execute(
                    """
                    SELECT catalog_id, kind, locator_ref, exclusive_owner,
                           attach_permitted, tree_id, recorded_at
                    FROM catalogs
                    WHERE tree_id = ? OR tree_id = ''
                    ORDER BY kind, recorded_at DESC
                    LIMIT ?
                    """,
                    [tree_id, int(limit)],
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT catalog_id, kind, locator_ref, exclusive_owner,
                           attach_permitted, tree_id, recorded_at
                    FROM catalogs
                    ORDER BY kind, recorded_at DESC
                    LIMIT ?
                    """,
                    [int(limit)],
                ).fetchall()
        finally:
            connection.close()
        catalogs = [
            {
                "catalog_id": row[0],
                "kind": row[1],
                "locator_ref": row[2],
                "exclusive_owner": row[3],
                "attach_permitted": bool(row[4]),
                "tree_id": row[5],
                "recorded_at": row[6],
            }
            for row in rows
        ]
        return {
            "schema": SCHEMA,
            "interface": INTERFACE,
            "catalogs": catalogs,
            "n": len(catalogs),
            "kinds": sorted({item["kind"] for item in catalogs}),
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
            "extra_gate_attached": False,
        }

    def project_ducklake(self) -> dict[str, Any]:
        root = self.ducklake_root
        if root is None:
            return {
                "status": "unconfigured",
                "reason_code": "ducklake_unconfigured",
                "completion_authority": False,
                "authoritative": False,
            }
        if not root.is_absolute():
            return {
                "status": "unavailable",
                "reason_code": "ducklake_root_must_be_absolute",
                "completion_authority": False,
                "authoritative": False,
            }
        try:
            import duckdb
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason_code": type(exc).__name__,
                "completion_authority": False,
                "authoritative": False,
            }
        catalog = root / "metadata.ducklake"
        data = root / "parquet"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "256MB"})
        try:
            connection.execute("SET autoinstall_known_extensions=false")
            connection.execute("SET autoload_known_extensions=false")
            connection.execute("LOAD ducklake")
            catalog_sql = str(catalog).replace("'", "''")
            data_sql = str(data).replace("'", "''")
            connection.execute(
                "ATTACH 'ducklake:"
                + catalog_sql
                + "' AS meta_lake (DATA_PATH '"
                + data_sql
                + "', DATA_INLINING_ROW_LIMIT 0)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS meta_lake.catalogs (
                    catalog_cid VARCHAR,
                    kind VARCHAR,
                    locator_ref VARCHAR,
                    exclusive_owner VARCHAR,
                    attach_permitted BOOLEAN,
                    tree_id VARCHAR,
                    recorded_at VARCHAR,
                    completion_authority BOOLEAN
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS meta_lake.identity_links (
                    link_cid VARCHAR,
                    subject_kind VARCHAR,
                    subject_ref VARCHAR,
                    catalog_id VARCHAR,
                    record_kind VARCHAR,
                    record_ref VARCHAR,
                    freshness_mtime_ns BIGINT,
                    recorded_at VARCHAR,
                    completion_authority BOOLEAN
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS meta_lake.capsule_bindings (
                    capsule_cid VARCHAR,
                    catalog_id VARCHAR,
                    subject_kind VARCHAR,
                    subject_ref VARCHAR,
                    recorded_at VARCHAR,
                    completion_authority BOOLEAN
                )
                """
            )
            source = _connect(self.duckdb_path)
            try:
                catalogs = source.execute(
                    """
                    SELECT catalog_cid, kind, locator_ref, exclusive_owner,
                           attach_permitted, tree_id, recorded_at
                    FROM catalogs
                    """
                ).fetchall()
                links = source.execute(
                    """
                    SELECT link_cid, subject_kind, subject_ref, catalog_id,
                           record_kind, record_ref, freshness_mtime_ns, recorded_at
                    FROM identity_links
                    """
                ).fetchall()
                bindings = source.execute(
                    """
                    SELECT capsule_cid, catalog_id, subject_kind, subject_ref, recorded_at
                    FROM capsule_bindings
                    """
                ).fetchall()
            finally:
                source.close()
            connection.execute("BEGIN TRANSACTION")
            try:
                for row in catalogs:
                    connection.execute(
                        """
                        INSERT INTO meta_lake.catalogs
                        SELECT ?, ?, ?, ?, ?, ?, ?, FALSE
                        WHERE NOT EXISTS (
                            SELECT 1 FROM meta_lake.catalogs WHERE catalog_cid = ?
                        )
                        """,
                        [*row, row[0]],
                    )
                for row in links:
                    connection.execute(
                        """
                        INSERT INTO meta_lake.identity_links
                        SELECT ?, ?, ?, ?, ?, ?, ?, ?, FALSE
                        WHERE NOT EXISTS (
                            SELECT 1 FROM meta_lake.identity_links WHERE link_cid = ?
                        )
                        """,
                        [*row, row[0]],
                    )
                for row in bindings:
                    connection.execute(
                        """
                        INSERT INTO meta_lake.capsule_bindings
                        SELECT ?, ?, ?, ?, ?, FALSE
                        WHERE NOT EXISTS (
                            SELECT 1 FROM meta_lake.capsule_bindings
                            WHERE capsule_cid = ? AND catalog_id = ?
                              AND subject_kind = ? AND subject_ref = ?
                        )
                        """,
                        [*row, row[0], row[1], row[2], row[3]],
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            count = connection.execute("SELECT count(*) FROM meta_lake.catalogs").fetchone()[0]
            link_count = connection.execute(
                "SELECT count(*) FROM meta_lake.identity_links"
            ).fetchone()[0]
            binding_count = connection.execute(
                "SELECT count(*) FROM meta_lake.capsule_bindings"
            ).fetchone()[0]
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason_code": type(exc).__name__,
                "error": str(exc)[:200],
                "completion_authority": False,
                "authoritative": False,
            }
        finally:
            connection.close()
        return {
            "status": "projected",
            "stored_catalogs": int(count),
            "stored_links": int(link_count),
            "stored_bindings": int(binding_count),
            "completion_authority": False,
            "authoritative": False,
        }


def _active() -> SupervisorMetaIndex | None:
    return SupervisorMetaIndex.from_env()


def register_catalog(**fields: Any) -> dict[str, Any]:
    index = _active()
    if index is None:
        return {
            "status": "skip",
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
        }
    return index.register_catalog(**fields)


def link_identity(**fields: Any) -> dict[str, Any]:
    index = _active()
    if index is None:
        return {
            "status": "skip",
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
        }
    return index.link_identity(**fields)


def compose_for_subject(
    *,
    subject_kind: str,
    subject_ref: str,
    store: SupervisorMetaIndex | None = None,
    limit: int = 64,
) -> dict[str, Any]:
    index = store if store is not None else _active()
    if index is None:
        return {
            "schema": SCHEMA,
            "linked": [],
            "n": 0,
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
        }
    return index.compose_for_subject(
        subject_kind=subject_kind, subject_ref=subject_ref, limit=limit
    )


def orchestration_view(
    *,
    tree_id: str = "",
    store: SupervisorMetaIndex | None = None,
    limit: int = 64,
) -> dict[str, Any]:
    index = store if store is not None else _active()
    if index is None:
        return {
            "schema": SCHEMA,
            "catalogs": [],
            "n": 0,
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
            "extra_gate_attached": False,
        }
    return index.orchestration_view(tree_id=tree_id, limit=limit)


def bind_supervisor_catalogs(
    *,
    tree_id: str = "",
    locators: Mapping[str, str] | None = None,
    taskboards: Sequence[Mapping[str, str]] | None = None,
    store: SupervisorMetaIndex | None = None,
) -> dict[str, Any]:
    index = store if store is not None else _active()
    if index is None:
        return {
            "status": "skip",
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
            "extra_gate_attached": False,
            "event_driven_qualified": True,
        }
    return index.bind_supervisor_catalogs(
        tree_id=tree_id, locators=locators, taskboards=taskboards
    )


def observe_path(
    path: str,
    *,
    mtime_ns: int | None = None,
    content_cid: str = "",
    tree_id: str = "",
    capsule_cid: str = "",
    extra_kinds: Sequence[str] = (),
    store: SupervisorMetaIndex | None = None,
) -> dict[str, Any]:
    index = store if store is not None else _active()
    if index is None:
        return {
            "status": "skip",
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
            "event_driven_qualified": True,
        }
    return index.observe_path(
        path,
        mtime_ns=mtime_ns,
        content_cid=content_cid,
        tree_id=tree_id,
        capsule_cid=capsule_cid,
        extra_kinds=extra_kinds,
    )


def compose_semantic_work(
    *,
    subject_kind: str,
    subject_ref: str,
    tree_id: str = "",
    store: SupervisorMetaIndex | None = None,
) -> dict[str, Any]:
    index = store if store is not None else _active()
    if index is None:
        return {
            "schema": SCHEMA,
            "linked": [],
            "catalogs": [],
            "n": 0,
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
            "extra_gate_attached": False,
            "capsule_composition": True,
            "formal_surfaces": [],
        }
    return index.compose_semantic_work(
        subject_kind=subject_kind, subject_ref=subject_ref, tree_id=tree_id
    )


def orchestrate_semantic_work(
    *,
    subject_kind: str = "tree_id",
    subject_ref: str = "",
    tree_id: str = "",
    path: str = "",
    mtime_ns: int | None = None,
    content_cid: str = "",
    capsule_cid: str = "",
    store: SupervisorMetaIndex | None = None,
) -> dict[str, Any]:
    index = store if store is not None else _active()
    if index is None:
        return {
            "schema": SCHEMA,
            "linked": [],
            "catalogs": [],
            "n": 0,
            "reason_code": "meta_index_unconfigured",
            "completion_authority": False,
            "decision_authority": False,
            "ducklake_authoritative": False,
            "event_driven_qualified": True,
            "extra_gate_attached": False,
            "capsule_composition": True,
            "formal_surfaces": [],
            "required_kinds": sorted(CATALOG_KINDS),
            "missing_kinds": sorted(CATALOG_KINDS),
            "catalogs_linked": False,
        }
    return index.orchestrate_semantic_work(
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        tree_id=tree_id,
        path=path,
        mtime_ns=mtime_ns,
        content_cid=content_cid,
        capsule_cid=capsule_cid,
    )


def mirror_world_model_record(record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        catalog = register_catalog(
            kind="world_model",
            locator_ref=str(os.environ.get("IPFS_ACCELERATE_PROGRAM_WORLD_DUCKDB") or "world_model"),
            repository_id=str(record.get("board") or "sawm"),
        )
        if catalog.get("status") == "skip":
            return catalog
        return link_identity(
            subject_kind="task_id",
            subject_ref=str(record.get("task_id") or record.get("record_cid") or ""),
            catalog_id=str(catalog.get("catalog_id") or ""),
            record_kind="world_model",
            record_ref=str(record.get("record_cid") or record.get("task_id") or ""),
            capsule_cid=str(record.get("capsule_cid") or ""),
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": type(exc).__name__,
            "completion_authority": False,
        }


def mirror_proof_certificate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        kind = "proof_certificate" if record.get("kind") == "zkp_certificate" else "proof_cache"
        catalog = register_catalog(
            kind=kind,
            locator_ref=str(
                os.environ.get("IPFS_ACCELERATE_PROOF_CERTIFICATE_DUCKDB") or "proof_certificates"
            ),
        )
        if catalog.get("status") == "skip":
            return catalog
        subject_kind = "receipt_id" if record.get("receipt_id") else "key_id"
        subject_ref = str(record.get("receipt_id") or record.get("key_id") or "")
        return link_identity(
            subject_kind=subject_kind,
            subject_ref=subject_ref,
            catalog_id=str(catalog.get("catalog_id") or ""),
            record_kind=kind,
            record_ref=str(record.get("record_cid") or subject_ref),
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": type(exc).__name__,
            "completion_authority": False,
        }


def mirror_capsule_record(
    *,
    capsule_cid: str,
    node_id: str = "",
    tree_id: str = "",
    dependency_cids: Sequence[str] = (),
) -> dict[str, Any]:
    try:
        catalog = register_catalog(
            kind="capsule",
            locator_ref=str(os.environ.get("IPFS_ACCELERATE_CAPSULE_INDEX") or "capsule"),
            tree_id=tree_id,
            project=False,
        )
        if catalog.get("status") == "skip":
            return catalog
        linked = [
            link_identity(
                subject_kind="capsule_cid",
                subject_ref=capsule_cid,
                catalog_id=str(catalog.get("catalog_id") or ""),
                record_kind="capsule",
                record_ref=node_id or capsule_cid,
                capsule_cid=capsule_cid,
                project=False,
            )
        ]
        if node_id:
            linked.append(
                link_identity(
                    subject_kind="record_cid",
                    subject_ref=node_id,
                    catalog_id=str(catalog.get("catalog_id") or ""),
                    record_kind="capsule",
                    record_ref=capsule_cid,
                    capsule_cid=capsule_cid,
                    project=False,
                )
            )
        for dep in tuple(dependency_cids)[:16]:
            linked.append(
                link_identity(
                    subject_kind="capsule_cid",
                    subject_ref=dep,
                    catalog_id=str(catalog.get("catalog_id") or ""),
                    record_kind="capsule_dependency",
                    record_ref=capsule_cid,
                    capsule_cid=capsule_cid,
                    project=False,
                )
            )
        index = _active()
        projection = index.project_ducklake() if index is not None else {
            "status": "unconfigured",
            "completion_authority": False,
            "authoritative": False,
        }
        return {
            "schema": SCHEMA,
            "capsule_cid": capsule_cid,
            "links": linked,
            "n": len(linked),
            "ducklake": projection,
            "completion_authority": False,
            "event_driven_qualified": True,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": type(exc).__name__,
            "completion_authority": False,
        }


def mirror_vector_index(
    *,
    tree_id: str,
    index_id: str,
    paths: Sequence[str] = (),
) -> dict[str, Any]:
    try:
        catalog = register_catalog(
            kind="vector",
            locator_ref=str(os.environ.get("IPFS_ACCELERATE_VECTOR_DUCKDB") or "vector"),
            tree_id=tree_id,
            project=False,
        )
        if catalog.get("status") == "skip":
            return catalog
        links = [
            link_identity(
                subject_kind="tree_id",
                subject_ref=tree_id,
                catalog_id=str(catalog.get("catalog_id") or ""),
                record_kind="vector",
                record_ref=index_id,
                project=False,
            )
        ]
        for path in tuple(paths)[:32]:
            links.append(
                link_identity(
                    subject_kind="path",
                    subject_ref=path,
                    catalog_id=str(catalog.get("catalog_id") or ""),
                    record_kind="vector",
                    record_ref=index_id,
                    project=False,
                )
            )
        index = _active()
        projection = index.project_ducklake() if index is not None else {
            "status": "unconfigured",
            "completion_authority": False,
            "authoritative": False,
        }
        return {
            "schema": SCHEMA,
            "index_id": index_id,
            "links": links,
            "n": len(links),
            "ducklake": projection,
            "completion_authority": False,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": type(exc).__name__,
            "completion_authority": False,
        }


def mirror_knowledge_graph(
    *,
    tree_id: str,
    graph_id: str,
) -> dict[str, Any]:
    try:
        catalog = register_catalog(
            kind="knowledge_graph",
            locator_ref=str(os.environ.get("IPFS_ACCELERATE_KNOWLEDGE_GRAPH_DUCKDB") or "knowledge_graph"),
            tree_id=tree_id,
            project=False,
        )
        if catalog.get("status") == "skip":
            return catalog
        linked = link_identity(
            subject_kind="tree_id",
            subject_ref=tree_id,
            catalog_id=str(catalog.get("catalog_id") or ""),
            record_kind="knowledge_graph",
            record_ref=graph_id,
        )
        return linked
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": type(exc).__name__,
            "completion_authority": False,
        }


def mirror_work_record(
    *,
    catalog_kind: str,
    record_kind: str,
    record_ref: str,
    tree_id: str = "",
    subject_kind: str = "tree_id",
    subject_ref: str = "",
    paths: Sequence[str] = (),
    locator_ref: str = "",
) -> dict[str, Any]:
    try:
        if catalog_kind not in CATALOG_KINDS:
            catalog_kind = "metadata"
        catalog = register_catalog(
            kind=catalog_kind,
            locator_ref=locator_ref or catalog_kind,
            tree_id=tree_id,
            project=False,
        )
        if catalog.get("status") == "skip":
            return catalog
        subject = subject_ref or tree_id or record_ref
        kind = subject_kind if subject_kind in SUBJECT_KINDS else "tree_id"
        links = [
            link_identity(
                subject_kind=kind,
                subject_ref=subject,
                catalog_id=str(catalog.get("catalog_id") or ""),
                record_kind=record_kind,
                record_ref=record_ref,
                capsule_cid=subject if kind == "capsule_cid" else "",
                project=False,
            )
        ]
        for path in tuple(paths)[:16]:
            links.append(
                link_identity(
                    subject_kind="path",
                    subject_ref=path,
                    catalog_id=str(catalog.get("catalog_id") or ""),
                    record_kind=record_kind,
                    record_ref=record_ref,
                    project=False,
                )
            )
        index = _active()
        projection = index.project_ducklake() if index is not None else {
            "status": "unconfigured",
            "completion_authority": False,
            "authoritative": False,
        }
        return {
            "schema": SCHEMA,
            "record_kind": record_kind,
            "record_ref": record_ref,
            "links": links,
            "n": len(links),
            "ducklake": projection,
            "completion_authority": False,
            "event_driven_qualified": True,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": type(exc).__name__,
            "completion_authority": False,
        }


def register_taskboard(
    *,
    board_id: str,
    exclusive_owner: str,
    locator_ref: str = "",
    tree_id: str = "",
) -> dict[str, Any]:
    return register_catalog(
        kind="taskboard",
        locator_ref=locator_ref or f"quack://{board_id}",
        exclusive_owner=exclusive_owner,
        repository_id=board_id,
        tree_id=tree_id,
    )
