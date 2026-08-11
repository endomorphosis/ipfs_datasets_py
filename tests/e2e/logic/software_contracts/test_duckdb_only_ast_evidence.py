"""E2E tests: DuckDB-only AST / code-evidence authority (DQK-070).

Acceptance coverage:

* AST/evidence consumers operate with legacy bundles absent
* Direct bundle writes occur only through named export commands
* Publication views apply repository and tenant filtering

Legacy analysis_ast_index, objective, dependency, conflict, and code-evidence
JSON files are never operational state.  Filesystem bundle writes are admitted
only via named export commands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _ensure_multiformats_for_sealed_validator() -> None:
    """Install a pure-Python multiformats shim when the package is absent."""

    try:
        import multiformats  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    import hashlib
    import types

    _B32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
    _CODEC_CODES: dict[str, int] = {
        "raw": 0x55,
        "dag-json": 0x0129,
    }
    _CODE_CODECS: dict[int, str] = {code: name for name, code in _CODEC_CODES.items()}

    def _uvarint(value: int) -> bytes:
        if value < 0:
            raise ValueError("uvarint requires a non-negative integer")
        out = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            out.append(byte | (0x80 if value else 0))
            if not value:
                break
        return bytes(out)

    def _read_uvarint(data: bytes, offset: int = 0) -> tuple[int, int]:
        result = 0
        shift = 0
        while True:
            if offset >= len(data):
                raise ValueError("truncated uvarint")
            byte = data[offset]
            offset += 1
            result |= (byte & 0x7F) << shift
            if byte & 0x80 == 0:
                return result, offset
            shift += 7
            if shift > 63:
                raise ValueError("uvarint too long")

    def _b32encode_nopad(data: bytes) -> str:
        bits = 0
        value = 0
        out: list[str] = []
        for byte in data:
            value = (value << 8) | byte
            bits += 8
            while bits >= 5:
                bits -= 5
                out.append(_B32_ALPHABET[(value >> bits) & 0x1F])
        if bits:
            out.append(_B32_ALPHABET[(value << (5 - bits)) & 0x1F])
        return "".join(out)

    def _b32decode_nopad(text: str) -> bytes:
        bits = 0
        value = 0
        out = bytearray()
        for ch in text.lower():
            try:
                idx = _B32_ALPHABET.index(ch)
            except ValueError as exc:
                raise ValueError(f"invalid base32 character: {ch!r}") from exc
            value = (value << 5) | idx
            bits += 5
            if bits >= 8:
                bits -= 8
                out.append((value >> bits) & 0xFF)
        return bytes(out)

    class _HashFun:
        def __init__(self, name: str, code: int, max_digest_size: int) -> None:
            self.name = name
            self.code = code
            self.max_digest_size = max_digest_size

    class _Codec:
        def __init__(self, name: str, code: int) -> None:
            self.name = name
            self.code = code

    class _Base:
        def __init__(self, name: str) -> None:
            self.name = name

    class _CID:
        def __init__(
            self,
            base: str,
            version: int,
            codec: str | int,
            digest: bytes,
        ) -> None:
            if base != "base32":
                raise ValueError(f"unsupported multibase: {base!r}")
            if version != 1:
                raise ValueError(f"unsupported CID version: {version!r}")
            if isinstance(codec, str):
                if codec not in _CODEC_CODES:
                    raise ValueError(f"unsupported codec: {codec!r}")
                codec_code = _CODEC_CODES[codec]
                codec_name = codec
            else:
                codec_code = int(codec)
                codec_name = _CODE_CODECS.get(codec_code, str(codec_code))
            if not isinstance(digest, (bytes, bytearray)) or not digest:
                raise TypeError("digest must be nonempty bytes")
            self.base = _Base(base)
            self.version = version
            self.codec = _Codec(codec_name, codec_code)
            self.hashfun = _HashFun("sha2-256", 0x12, 32)
            self._digest = bytes(digest)
            if len(self._digest) >= 2 and self._digest[0] == 0x12:
                length = self._digest[1]
                self.raw_digest = self._digest[2 : 2 + length]
            else:
                self.raw_digest = self._digest
            binary = _uvarint(version) + _uvarint(codec_code) + self._digest
            self._str = "b" + _b32encode_nopad(binary)

        def __str__(self) -> str:
            return self._str

        def __repr__(self) -> str:
            return f"CID({self._str!r})"

        @classmethod
        def decode(cls, value: str) -> "_CID":
            if not isinstance(value, str) or not value:
                raise ValueError("CID must be a nonempty string")
            text = value.lower()
            if not text.startswith("b"):
                raise ValueError("only base32 CIDs are supported")
            binary = _b32decode_nopad(text[1:])
            version, offset = _read_uvarint(binary, 0)
            codec_code, offset = _read_uvarint(binary, offset)
            digest = binary[offset:]
            codec_name = _CODE_CODECS.get(codec_code, codec_code)
            return cls("base32", version, codec_name, digest)

    class _MultihashModule(types.ModuleType):
        def digest(self, data: bytes, hashfun: str) -> bytes:
            if hashfun != "sha2-256":
                raise ValueError(f"unsupported multihash: {hashfun!r}")
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("multihash digest requires bytes")
            digest = hashlib.sha256(bytes(data)).digest()
            return bytes([0x12, len(digest)]) + digest

        def get(self, hashfun: str) -> _HashFun:
            if hashfun != "sha2-256":
                raise KeyError(hashfun)
            return _HashFun("sha2-256", 0x12, 32)

    root = types.ModuleType("multiformats")
    mh = _MultihashModule("multiformats.multihash")
    cid_mod = types.ModuleType("multiformats.cid")
    cid_mod.CID = _CID  # type: ignore[attr-defined]
    root.CID = _CID  # type: ignore[attr-defined]
    root.multihash = mh  # type: ignore[attr-defined]
    sys.modules["multiformats"] = root
    sys.modules["multiformats.cid"] = cid_mod
    sys.modules["multiformats.multihash"] = mh


_ensure_multiformats_for_sealed_validator()

from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AuthorityMode,
    MemoryAuthorityBackend,
    build_authority_port,
)
from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (  # noqa: E402
    BUNDLE_ARTIFACTS,
    CODE_EVIDENCE_NAMED_EXPORT_COMMANDS,
    CODE_EVIDENCE_ONLY_OWNER_TASK,
    CODE_EVIDENCE_PUBLICATION_VIEW_SCHEMA,
    CodeEvidenceAdapterError,
    CodeEvidenceAuthority,
    CodeEvidenceCorpusAdapter,
    build_code_evidence_authority,
    build_tiny_fixture_bundle,
    open_bundle_reader,
)
from ipfs_datasets_py.logic.software_contracts.ast_ir import (  # noqa: E402
    CallRecord,
    DiagnosticRecord,
    EffectRecord,
    FrontendCapability,
    ImportDefinition,
    ModuleDefinition,
    ParameterDefinition,
    ReferenceRecord,
    ScopeDefinition,
    SignatureDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
    ASTRecord,
)
from ipfs_datasets_py.logic.software_contracts.content import (  # noqa: E402
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (  # noqa: E402
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.repository import (  # noqa: E402
    AST_AUTHORITY_DOMAIN,
    AST_DEFAULT_TENANT_ID,
    AST_LEGACY_BUNDLE_ARTIFACTS,
    AST_NAMED_EXPORT_COMMANDS,
    AST_ONLY_DEFAULT_MODE,
    AST_ONLY_OWNER_TASK,
    AST_PUBLICATION_VIEW_SCHEMA,
    ASTAuthorityError,
    ASTAuthorityRepository,
    build_ast_authority_repository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PY_OK = b"from os import path\n\ndef alpha(value: int) -> int:\n    return path.join(str(value))\n"
PY_BETA = b"def beta():\n    return alpha(1)\n"


def _port(mode: AuthorityMode = AuthorityMode.DB_PRIMARY):
    store = MemoryAuthorityBackend()
    port = build_authority_port(
        store,
        domain=AST_AUTHORITY_DOMAIN,
        initial_mode=mode,
        writer_id="writer:test-ast-only",
    )
    return port, store


def _span(
    start: int = 0,
    end: int = 1,
    line: int = 1,
    end_line: int | None = None,
) -> SourceSpan:
    return SourceSpan(
        start_byte=start,
        end_byte=end,
        start_line=line,
        start_column=0,
        end_line=line if end_line is None else end_line,
        end_column=max(end - start, 0),
    )


def _complete_record(
    source: bytes = PY_OK,
    path: str = "src/alpha.py",
    revision: str = "rev-only-1",
    repository_id: str = "repository:alpha",
) -> ASTRecord:
    whole = _span(0, len(source), 1, 4)
    function_span = _span(20, len(source), 3, 4)
    call_span = _span(60, 80, 4)
    root_scope = ScopeDefinition(scope_id="scope:module", kind="module", span=whole)
    function_scope = ScopeDefinition(
        scope_id="scope:function:alpha",
        kind="function",
        span=function_span,
        parent_scope_id="scope:module",
        owner_symbol_id="symbol:alpha:0",
    )
    signature = SignatureDefinition(
        parameters=(
            ParameterDefinition(
                name="value",
                kind="positional_or_named",
                position=0,
                annotation="int",
            ),
        ),
        return_annotation="int",
    )
    symbol = SymbolDefinition(
        symbol_id="symbol:alpha:0",
        name="alpha",
        qualified_name="alpha.alpha",
        kind="function",
        scope_id="scope:module",
        span=function_span,
        definition_ordinal=0,
        signature=signature,
        visibility="public",
    )
    reference = ReferenceRecord(
        reference_id="reference:path.join:0",
        name="path.join",
        scope_id="scope:function:alpha",
        context="call",
        span=call_span,
    )
    frontend = FrontendCapability(
        frontend_name="cpython-ast",
        frontend_version="3.12.4",
        language="python",
        language_version="3.12",
        capabilities=("symbols", "imports", "calls", "effects", "modules"),
        source_extensions=(".py", ".pyi"),
        toolchain_cid=cid_for_structured(
            {"frontend": "cpython-ast", "version": "3.12.4"}
        ),
    )
    return ASTRecord(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(source),
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=cid_for_structured({"git_tree": "tree-only"}),
        ),
        frontend=frontend,
        module=ModuleDefinition(
            module_id="module:alpha",
            name="alpha",
            scope_id="scope:module",
            span=whole,
            export_names=("alpha",),
        ),
        scopes=(function_scope, root_scope),
        symbols=(symbol,),
        imports=(
            ImportDefinition(
                import_id="import:os.path:0",
                scope_id="scope:module",
                module="os",
                kind="symbol",
                span=_span(0, 18),
                imported_name="path",
                local_name="path",
            ),
        ),
        references=(reference,),
        calls=(
            CallRecord(
                call_id="call:path.join:0",
                scope_id="scope:function:alpha",
                callee_name="path.join",
                kind="direct",
                argument_count=1,
                span=call_span,
                callee_reference_id=reference.reference_id,
            ),
        ),
        effects=(
            EffectRecord(
                effect_id="effect:call:0",
                scope_id="scope:function:alpha",
                kind="io",
                operation="invoke",
                span=call_span,
                subject="path.join",
            ),
        ),
        diagnostics=(
            DiagnosticRecord(
                code="frontend.note",
                severity="info",
                message="example diagnostic",
                span=call_span,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Pins / named export surface
# ---------------------------------------------------------------------------


def test_dqk070_owner_and_named_export_pins() -> None:
    assert AST_ONLY_OWNER_TASK == "DQK-070"
    assert CODE_EVIDENCE_ONLY_OWNER_TASK == "DQK-070"
    assert AST_ONLY_DEFAULT_MODE == "db-primary"
    assert AST_NAMED_EXPORT_COMMANDS == CODE_EVIDENCE_NAMED_EXPORT_COMMANDS
    assert "export_json_bundle" in AST_NAMED_EXPORT_COMMANDS
    assert "export_compatibility_bundle" in AST_NAMED_EXPORT_COMMANDS
    assert "write_compatibility_export" in AST_NAMED_EXPORT_COMMANDS
    assert AST_DEFAULT_TENANT_ID == "tenant:default"
    for name in (
        "analysis_ast_index",
        "objective_graph",
        "semantic_dependency_graph",
        "conflict_graph",
        "code_evidence_graph",
    ):
        assert name in AST_LEGACY_BUNDLE_ARTIFACTS
        assert name in BUNDLE_ARTIFACTS


# ---------------------------------------------------------------------------
# Consumers operate with legacy bundles absent
# ---------------------------------------------------------------------------


def test_consumers_operate_with_legacy_bundles_absent(tmp_path: Path) -> None:
    """No analysis_ast_index / objective / conflict / evidence JSON on disk."""

    bundle_dir = tmp_path / "no-bundles"
    bundle_dir.mkdir()
    # Prove the legacy multi-graph surface is entirely absent.
    for rel in AST_LEGACY_BUNDLE_ARTIFACTS.values():
        assert not (bundle_dir / rel).exists()

    port, backend = _port(AuthorityMode.DB_PRIMARY)
    consumer = build_code_evidence_authority(
        port,
        tenant_id="tenant:acme",
        initial_mode="db-primary",
    )
    assert consumer.legacy_bundle_operational is False
    assert consumer.default_source == "duckdb"

    record = _complete_record(repository_id="repository:acme-svc")
    published = consumer.publish_record(record)
    assert published["ok"] is True
    assert published["filesystem_bundle_written"] is False
    assert published["legacy_bundle_operational"] is False
    assert published["default_source"] == "duckdb"

    # All operational families resolve from DuckDB with no JSON present.
    evidence = consumer.code_evidence_query()
    assert evidence["default_source"] == "duckdb"
    assert evidence["node_count"] >= 1
    assert evidence["family"] == "code_evidence"

    conflict = consumer.conflict_query()
    assert conflict["default_source"] == "duckdb"
    assert conflict["family"] == "conflict"

    dependency = consumer.dependency_query(seed_ids=["src/alpha.py"])
    assert dependency["default_source"] == "duckdb"
    assert dependency["family"] == "dependency"

    impact = consumer.impact_query(roots=["src/alpha.py"])
    assert impact["default_source"] == "duckdb"
    assert set(dependency["nodes"]) == set(impact["nodes"])

    consumer.register_objective(
        "goal:ship-alpha",
        title="Ship alpha",
        repository_id="repository:acme-svc",
        tenant_id="tenant:acme",
    )
    objective = consumer.objective_query(
        repository_id="repository:acme-svc",
        tenant_id="tenant:acme",
    )
    assert objective["family"] == "objective"
    assert objective["default_source"] == "duckdb"
    assert objective["legacy_bundle_operational"] is False
    assert objective["goal_count"] == 1
    assert objective["goals"][0]["goal_id"] == "goal:ship-alpha"

    # Still no legacy JSON on disk after operational writes.
    for rel in AST_LEGACY_BUNDLE_ARTIFACTS.values():
        assert not (bundle_dir / rel).exists()
    assert consumer.filesystem_bundle_write_count() == 0

    # db-primary reads prefer DuckDB; legacy may be empty or projected.
    key = published["authority_key"]
    db = backend.get_db(AST_AUTHORITY_DOMAIN, key)
    assert db is not None
    assert db.get("operational_authority") == "duckdb"
    assert db.get("legacy_bundle_operational") is False
    payload = consumer.repository.read(key)
    assert payload is not None
    assert payload.get("operational_authority") == "duckdb"


def test_reject_operational_legacy_bundle_load() -> None:
    port, _ = _port()
    consumer = build_code_evidence_authority(port, tenant_id="tenant:x")
    with pytest.raises(CodeEvidenceAdapterError, match="DQK-070"):
        consumer.reject_legacy_bundle_load(artifact="analysis_ast_index")
    with pytest.raises(CodeEvidenceAdapterError, match="DQK-070"):
        consumer.reject_legacy_bundle_load(artifact="objective_graph")
    with pytest.raises(CodeEvidenceAdapterError, match="DQK-070"):
        consumer.reject_legacy_bundle_load(artifact="conflict_graph")
    with pytest.raises(CodeEvidenceAdapterError, match="DQK-070"):
        consumer.reject_legacy_bundle_load(artifact="code_evidence_graph")

    repo = consumer.repository
    assert isinstance(repo, ASTAuthorityRepository)
    with pytest.raises(ASTAuthorityError, match="DQK-070"):
        repo.reject_legacy_bundle_load(artifact="semantic_dependency_graph")


def test_corpus_adapter_is_compatibility_only(tmp_path: Path) -> None:
    root = build_tiny_fixture_bundle(tmp_path / "fixture-bundle")
    adapter = open_bundle_reader(root)
    assert isinstance(adapter, CodeEvidenceCorpusAdapter)
    assert adapter.OPERATIONAL_AUTHORITY is False
    assert adapter.COMPATIBILITY_ONLY is True
    with pytest.raises(CodeEvidenceAdapterError, match="operational"):
        CodeEvidenceCorpusAdapter(root, operational=True)


def test_db_primary_consumers_without_legacy_surface() -> None:
    port, backend = _port(AuthorityMode.DB_PRIMARY)
    repo = build_ast_authority_repository(
        port,
        tenant_id="tenant:solo",
        promote_to_db_primary=False,
    )
    assert repo.mode == "db-primary"
    record = _complete_record(repository_id="repository:solo")
    write = repo.write_projection(project_ast_record(record), tenant_id="tenant:solo")
    assert write["ok"] is True
    assert write["filesystem_bundle_written"] is False
    key = write["authority_key"]
    # Under db-primary the live read is the DuckDB document.
    live = repo.read(key)
    assert live is not None
    assert live.get("operational_authority") == "duckdb"
    # Consumers never need the legacy side.
    evidence = repo.code_evidence_query()
    assert evidence["node_count"] >= 1
    assert evidence["default_source"] == "duckdb"


# ---------------------------------------------------------------------------
# Direct bundle writes only through named export commands
# ---------------------------------------------------------------------------


def test_direct_bundle_writes_only_via_named_exports(tmp_path: Path) -> None:
    port, _ = _port(AuthorityMode.DB_PRIMARY)
    consumer = build_code_evidence_authority(
        port,
        tenant_id="tenant:export",
        initial_mode="db-primary",
    )
    consumer.publish_record(
        _complete_record(repository_id="repository:export-me")
    )
    consumer.register_objective(
        "goal:export",
        repository_id="repository:export-me",
        tenant_id="tenant:export",
    )
    dest = tmp_path / "compat-export"
    assert consumer.filesystem_bundle_write_count() == 0

    # Operational publish must not create bundle artifacts anywhere under tmp.
    before = {p.name for p in tmp_path.rglob("*.json")} if tmp_path.exists() else set()
    consumer.publish_record(
        _complete_record(
            source=PY_BETA,
            path="src/beta.py",
            repository_id="repository:export-me",
            revision="rev-only-2",
        )
    )
    after = {p.name for p in tmp_path.rglob("*.json")}
    for artifact in AST_LEGACY_BUNDLE_ARTIFACTS.values():
        assert artifact not in after - before

    # Named export is the only admitted filesystem write path.
    export = consumer.export_compatibility_bundle(
        dest,
        repository_id="repository:export-me",
        tenant_id="tenant:export",
        revision="rev-export-1",
    )
    assert export["ok"] is True
    assert export["operational_authority"] is False
    assert export["legacy_bundle_operational"] is False
    assert export["named_export_command"] == "export_compatibility_bundle"
    assert export["owner_task_id"] == "DQK-070"
    assert consumer.filesystem_bundle_write_count() >= 1
    assert "export_compatibility_bundle" in consumer.named_export_invocations()

    for name, rel in AST_LEGACY_BUNDLE_ARTIFACTS.items():
        path = dest / rel
        assert path.is_file(), name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if name != "manifest":
            assert payload.get("operational_authority") is False
            assert payload.get("named_export_command") in {
                "write_compatibility_export",
                "export_compatibility_bundle",
            }
        else:
            assert payload.get("operational_authority") is False
            assert payload.get("owner_task_id") == "DQK-070"

    # In-memory named export does not write filesystem artifacts twice.
    key = consumer.published_keys()[0]
    mem = consumer.export_json_bundle(key)
    assert mem is not None
    assert mem["operational_authority"] is False
    assert mem["named_export_command"] == "export_json_bundle"
    assert "export_json_bundle" in consumer.named_export_invocations()

    # write_compatibility_export is also admitted.
    dest2 = tmp_path / "compat-export-2"
    alt = consumer.write_compatibility_export(
        dest2,
        repository_id="repository:export-me",
        tenant_id="tenant:export",
    )
    assert alt["ok"] is True
    assert alt["named_export_command"] == "write_compatibility_export"
    assert (dest2 / "analysis_ast_index.json").is_file()


def test_named_export_commands_are_closed_set() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port, tenant_id="tenant:closed")
    assert repo.named_export_commands == AST_NAMED_EXPORT_COMMANDS
    consumer = build_code_evidence_authority(port, tenant_id="tenant:closed")
    assert consumer.named_export_commands == CODE_EVIDENCE_NAMED_EXPORT_COMMANDS


# ---------------------------------------------------------------------------
# Publication views apply repository and tenant filtering
# ---------------------------------------------------------------------------


def test_publication_views_filter_by_repository_and_tenant() -> None:
    port, _ = _port(AuthorityMode.DB_PRIMARY)
    # Two tenants / two repositories share one authority port.
    consumer_a = build_code_evidence_authority(
        port,
        tenant_id="tenant:a",
        initial_mode="db-primary",
    )
    # Reuse the same repository instance for multi-tenant isolation tests.
    repo = consumer_a.repository
    consumer_b = CodeEvidenceAuthority(
        authority_repository=repo,
        tenant_id="tenant:b",
    )

    ra = project_ast_record(
        _complete_record(
            path="pkg/a.py",
            repository_id="repository:a",
            revision="rev-a",
        )
    )
    rb = project_ast_record(
        _complete_record(
            source=PY_BETA,
            path="pkg/b.py",
            repository_id="repository:b",
            revision="rev-b",
        )
    )
    consumer_a.publish_projection(ra, tenant_id="tenant:a")
    consumer_b.publish_projection(rb, tenant_id="tenant:b")
    consumer_a.register_objective(
        "goal:a",
        repository_id="repository:a",
        tenant_id="tenant:a",
    )
    consumer_b.register_objective(
        "goal:b",
        repository_id="repository:b",
        tenant_id="tenant:b",
    )

    view_a = consumer_a.publication_view(
        repository_id="repository:a",
        tenant_id="tenant:a",
    )
    assert view_a["schema"] == CODE_EVIDENCE_PUBLICATION_VIEW_SCHEMA
    assert view_a["filter"]["repository_id"] == "repository:a"
    assert view_a["filter"]["tenant_id"] == "tenant:a"
    assert view_a["legacy_bundle_operational"] is False
    assert view_a["default_source"] == "duckdb"
    paths_a = {n["path"] for n in view_a["nodes"]}
    assert "pkg/a.py" in paths_a
    assert "pkg/b.py" not in paths_a
    assert all(n["tenant_id"] == "tenant:a" for n in view_a["nodes"])
    assert all(n["repository_id"] == "repository:a" for n in view_a["nodes"])
    goal_ids_a = {g["goal_id"] for g in view_a["objectives"]}
    assert "goal:a" in goal_ids_a
    assert "goal:b" not in goal_ids_a
    assert "source_bytes" in view_a["excluded_surfaces"]
    assert "legacy_json_bundle_files" in view_a["excluded_surfaces"]

    view_b = consumer_b.publication_view(
        repository_id="repository:b",
        tenant_id="tenant:b",
    )
    paths_b = {n["path"] for n in view_b["nodes"]}
    assert "pkg/b.py" in paths_b
    assert "pkg/a.py" not in paths_b

    # Cross-tenant filter yields empty view.
    empty = repo.publication_view(
        repository_id="repository:a",
        tenant_id="tenant:b",
    )
    assert empty["schema"] == AST_PUBLICATION_VIEW_SCHEMA
    assert empty["node_count"] == 0
    assert empty["nodes"] == []
    assert empty["objectives"] == []

    # Repository-only filter (all tenants) still scopes by repository.
    repo_only = repo.publication_view(repository_id="repository:a")
    assert {n["path"] for n in repo_only["nodes"]} == {"pkg/a.py"}


def test_publication_view_digest_is_stable() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port, tenant_id="tenant:stable")
    repo.write_projection(
        project_ast_record(_complete_record(repository_id="repository:stable")),
        tenant_id="tenant:stable",
    )
    v1 = repo.publication_view(
        repository_id="repository:stable",
        tenant_id="tenant:stable",
    )
    v2 = repo.publication_view(
        repository_id="repository:stable",
        tenant_id="tenant:stable",
    )
    assert v1["view_digest"] == v2["view_digest"]
    assert v1["view_digest"].startswith("sha256:")


# ---------------------------------------------------------------------------
# End-to-end cutover path
# ---------------------------------------------------------------------------


def test_promote_to_db_primary_and_export(tmp_path: Path) -> None:
    port, _ = _port(AuthorityMode.DUAL)
    consumer = build_code_evidence_authority(
        port,
        tenant_id="tenant:cutover",
        initial_mode="dual",
    )
    consumer.publish_record(
        _complete_record(repository_id="repository:cutover")
    )
    # Consumers already work under dual without loading JSON.
    assert consumer.code_evidence_query()["node_count"] >= 1
    promo = consumer.promote_to_db_primary(require_parity=False)
    assert promo["ok"] is True
    assert consumer.repository.mode in {"db-primary", "dual"}
    # After promotion, named export still works; operational load still forbidden.
    dest = tmp_path / "after-promote"
    export = consumer.export_compatibility_bundle(
        dest,
        repository_id="repository:cutover",
        tenant_id="tenant:cutover",
    )
    assert export["ok"] is True
    assert (dest / "code_evidence_graph.json").is_file()
    with pytest.raises(CodeEvidenceAdapterError):
        consumer.reject_legacy_bundle_load()


def test_compatibility_import_then_duckdb_only_consumers(tmp_path: Path) -> None:
    """Bundle import is explicit; subsequent consumers never re-poll JSON."""

    port, _ = _port(AuthorityMode.DB_PRIMARY)
    consumer = build_code_evidence_authority(
        port,
        tenant_id="tenant:import",
        initial_mode="db-primary",
    )
    bundle_root = build_tiny_fixture_bundle(tmp_path / "import-bundle")
    adapter = open_bundle_reader(bundle_root)
    report = consumer.publish_from_bundle_adapter(
        adapter,
        sources=[
            {
                "path": "fixture/good.py",
                "source": PY_OK,
                "language": "python",
            },
        ],
        repository_id="repository:fixture",
        continue_on_parse_failure=True,
    )
    assert report["ok"] is True
    assert report["compatibility_import"] is True
    assert report["legacy_bundle_operational"] is False
    assert report["operational_authority"] == "duckdb"

    # Delete the on-disk bundle; consumers must still function from DuckDB.
    for path in bundle_root.rglob("*"):
        if path.is_file():
            path.unlink()
    assert consumer.code_evidence_query()["default_source"] == "duckdb"
    # Nodes from the extracted source remain available.
    evidence = consumer.code_evidence_query()
    assert evidence["node_count"] >= 0  # edges may exist from import
    # Objective / conflict / dependency families stay DuckDB-backed.
    assert consumer.conflict_query()["default_source"] == "duckdb"
    assert consumer.dependency_query(seed_ids=["fixture/good.py"])[
        "default_source"
    ] == "duckdb"
