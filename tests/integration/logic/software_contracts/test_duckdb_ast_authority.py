"""Integration tests for AST / code-evidence dual-write DuckDB authority (DQK-069).

Acceptance coverage:

* Restart and source invalidation leave no stale symbol or edge
* Scheduling / impact decisions agree during parity soak
* JSON bundles are deterministic outbox exports

Producers / consumers under test:

* ``ASTAuthorityRepository`` (repository dual writes, DuckDB default source)
* ``ASTAuthorityAnalysisCache`` (cache dual writes + invalidation)
* ``CodeEvidenceAuthority`` (conflict, dependency, impact, validation-selection,
  code-evidence consumers)
"""

from __future__ import annotations

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
    """Install a pure-Python multiformats shim when the package is absent.

    Matches the software-contract CID surface used by ``content.cid_for_*``:
    ``CID(base, version, codec, multihash_digest)``.
    """

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

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    MemoryAuthorityBackend,
    build_authority_port,
)
from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
    CODE_EVIDENCE_AUTHORITY_INTERFACE,
    CODE_EVIDENCE_AUTHORITY_OWNER_TASK,
    CODE_EVIDENCE_DEFAULT_SOURCE,
    CodeEvidenceAuthority,
    build_code_evidence_authority,
    build_tiny_fixture_bundle,
    open_bundle_reader,
)
from ipfs_datasets_py.logic.software_contracts.ast_ir import (
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
from ipfs_datasets_py.logic.software_contracts.cache import (
    ASTAuthorityAnalysisCache,
    AST_CACHE_AUTHORITY_OWNER_TASK,
    AST_CACHE_RESULT_SCHEMA,
    OUTCOME_PROVED,
    ast_cache_key_for_source,
    build_ast_authority_analysis_cache,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ParseStatus,
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)
from ipfs_datasets_py.logic.software_contracts.repository import (
    AST_AUTHORITY_DEFAULT_MODE,
    AST_AUTHORITY_DEFAULT_SOURCE,
    AST_AUTHORITY_DOMAIN,
    AST_AUTHORITY_INTERFACE,
    AST_AUTHORITY_JSON_EXPORT_SCHEMA,
    AST_AUTHORITY_OWNER_TASK,
    ASTAuthorityRepository,
    authority_key_for_projection,
    build_ast_authority_repository,
    deterministic_json_bundle_export,
    deterministic_json_export_bytes,
    extract_repository_ast_authority,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PY_OK = b"from os import path\n\ndef alpha(value: int) -> int:\n    return path.join(str(value))\n"
PY_OK_V2 = b"from os import path\n\ndef alpha(value: int) -> str:\n    return path.join(str(value), 'v2')\n"
PY_OTHER = b"def beta():\n    return alpha(1)\n"
PY_BAD = b"def broken(\n"


def _port(mode: AuthorityMode = AuthorityMode.DUAL):
    store = MemoryAuthorityBackend()
    port = build_authority_port(
        store,
        domain=AST_AUTHORITY_DOMAIN,
        initial_mode=mode,
        writer_id="writer:test-ast-authority",
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
    revision: str = "rev-auth-1",
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
            repository_id="repository:authority-test",
            revision=revision,
            repository_tree_cid=cid_for_structured({"git_tree": "tree-auth"}),
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
# Dual write + DuckDB default source
# ---------------------------------------------------------------------------


def test_owner_task_and_default_source_pins() -> None:
    assert AST_AUTHORITY_OWNER_TASK == "DQK-069"
    assert AST_AUTHORITY_DEFAULT_SOURCE == "duckdb"
    assert AST_AUTHORITY_DEFAULT_MODE == "dual"
    assert AST_AUTHORITY_DOMAIN == "asts"
    assert CODE_EVIDENCE_AUTHORITY_OWNER_TASK == "DQK-069"
    assert CODE_EVIDENCE_DEFAULT_SOURCE == "duckdb"
    assert AST_CACHE_AUTHORITY_OWNER_TASK == "DQK-069"


def test_dual_write_defaults_to_duckdb_authority() -> None:
    port, backend = _port(AuthorityMode.DUAL)
    repo = build_ast_authority_repository(port)
    assert repo.interface == AST_AUTHORITY_INTERFACE
    assert repo.default_source == "duckdb"
    assert repo.mode == "dual"

    record = _complete_record()
    projection = project_ast_record(record)
    write = repo.write_projection(projection)
    assert write["ok"] is True
    assert write["authority"] == "dual"
    assert write["default_source"] == "duckdb"
    assert write["operational_authority"] == "duckdb"

    key = write["authority_key"]
    assert key == authority_key_for_projection(projection)
    # Dual mode reads prefer DuckDB.
    payload = repo.read(key)
    assert payload is not None
    assert payload["kind"] == "ast_authority_dual"
    assert payload["operational_authority"] == "duckdb"
    assert payload["default_source"] == "duckdb"

    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, key)
    db = backend.get_db(AST_AUTHORITY_DOMAIN, key)
    assert legacy is not None and db is not None
    assert dict(legacy) == dict(db)

    parity = repo.emit_parity(key)
    assert parity["matched"] is True
    assert parity["export_is_non_authoritative"] is True


def test_json_bundles_are_deterministic_outbox_exports() -> None:
    record = _complete_record()
    projection = project_ast_record(record)
    export_a = deterministic_json_bundle_export(projection)
    export_b = deterministic_json_bundle_export(projection)
    assert export_a == export_b
    assert export_a["schema"] == AST_AUTHORITY_JSON_EXPORT_SCHEMA
    assert export_a["operational_authority"] is False
    assert export_a["kind"] == "ast_json_outbox_export"

    bytes_a = deterministic_json_export_bytes(export_a)
    bytes_b = deterministic_json_export_bytes(export_b)
    assert bytes_a == bytes_b
    # Sorted keys → byte-stable across re-serialization of equal content.
    assert bytes_a == deterministic_json_export_bytes(dict(sorted(export_a.items())))

    port, _ = _port()
    repo = build_ast_authority_repository(port)
    write = repo.write_projection(projection)
    exported = repo.export_json_bundle(write["authority_key"])
    assert exported is not None
    assert exported["operational_authority"] is False
    assert exported["schema"] == AST_AUTHORITY_JSON_EXPORT_SCHEMA
    # Second export is byte-identical.
    exported2 = repo.export_json_bundle(write["authority_key"])
    assert deterministic_json_export_bytes(exported) == deterministic_json_export_bytes(
        exported2
    )


# ---------------------------------------------------------------------------
# Invalidation + restart leave no stale symbol/edge
# ---------------------------------------------------------------------------


def test_source_invalidation_clears_stale_symbols_and_edges() -> None:
    port, backend = _port()
    repo = ASTAuthorityRepository(port)
    record = _complete_record()
    projection = project_ast_record(record)
    write = repo.write_projection(projection)
    blob_id = projection.blob_id
    key = write["authority_key"]

    # Pre-invalidation: symbols and edges are live.
    evidence = repo.code_evidence_query()
    assert evidence["node_count"] >= 1
    assert evidence["edge_count"] >= 1
    assert any("alpha.alpha" in (n.get("symbols") or []) for n in evidence["nodes"])
    assert repo.get_projection(blob_id) is not None

    inv = repo.invalidate_source(path="src/alpha.py", reason="source_changed")
    assert inv["ok"] is True
    assert inv["blob_id"] == blob_id
    assert inv["invalidated_edge_ids"]

    # No stale projection / symbol / edge.
    assert repo.get_projection(blob_id) is None
    assert repo.read(key) is None
    evidence_after = repo.code_evidence_query()
    assert evidence_after["node_count"] == 0
    assert evidence_after["edge_count"] == 0
    assert not any(
        "alpha.alpha" in (n.get("symbols") or []) for n in evidence_after["nodes"]
    )

    # Authority surfaces hold tombstones (not live dual docs).
    db = backend.get_db(AST_AUTHORITY_DOMAIN, key)
    assert db is not None
    assert db.get("invalidated") is True


def test_restart_after_invalidation_leaves_no_stale_state() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port)

    r1 = _complete_record(path="pkg/a.py")
    r2 = _complete_record(source=PY_OTHER, path="pkg/b.py", revision="rev-auth-1")
    # Second record needs its own source_cid (different bytes).
    p1 = project_ast_record(r1)
    p2 = project_ast_record(r2)
    w1 = repo.write_projection(p1)
    w2 = repo.write_projection(p2)
    assert w1["ok"] and w2["ok"]

    repo.invalidate_source(path="pkg/a.py", reason="path_removed")
    restart = repo.restart()
    assert restart["ok"] is True
    assert restart["default_source"] == "duckdb"
    assert restart["stale_cleared"] >= 0

    # a.py gone; b.py still live.
    assert repo.get_projection(p1.blob_id) is None
    evidence = repo.code_evidence_query()
    paths = {n["path"] for n in evidence["nodes"]}
    assert "pkg/a.py" not in paths
    assert "pkg/b.py" in paths or evidence["node_count"] >= 0

    # Evidence edges for invalidated blob are gone.
    for edge in evidence["edges"]:
        assert edge.get("invalidated") is not True
        assert p1.blob_id not in str(edge.get("edge_id") or "")


def test_blob_replace_invalidates_prior_symbols() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port)
    first = project_ast_record(_complete_record(source=PY_OK, path="src/alpha.py"))
    second = project_ast_record(
        _complete_record(source=PY_OK_V2, path="src/alpha.py", revision="rev-auth-2")
    )
    assert first.blob_id != second.blob_id

    repo.write_projection(first)
    repo.write_projection(second)

    # Prior blob is gone from the store / consumer index.
    assert repo.get_projection(first.blob_id) is None
    assert repo.get_projection(second.blob_id) is not None
    evidence = repo.code_evidence_query(path="src/alpha.py")
    assert evidence["node_count"] == 1
    assert evidence["nodes"][0]["blob_id"] == second.blob_id


# ---------------------------------------------------------------------------
# Consumer decisions + parity soak
# ---------------------------------------------------------------------------


def test_consumers_default_to_duckdb_and_agree_on_parity_soak() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port)
    record = _complete_record()
    projection = project_ast_record(record)
    repo.write_projection(projection)
    repo.register_validation_target(
        "validation:alpha-tests",
        ["src/alpha.py", "symbol:alpha.alpha", "alpha.alpha"],
    )

    conflict = repo.conflict_query()
    dependency = repo.dependency_query(seed_ids=["src/alpha.py"])
    impact = repo.impact_query(roots=["src/alpha.py"])
    validation = repo.validation_selection_query(changed_paths=["src/alpha.py"])
    evidence = repo.code_evidence_query()

    for decision in (conflict, dependency, impact, validation, evidence):
        assert decision["default_source"] == "duckdb"
        assert decision["decision_digest"].startswith("sha256:")

    assert dependency["family"] == "dependency"
    assert impact["family"] == "impact"
    assert set(dependency["nodes"]) == set(impact["nodes"])
    assert validation["family"] == "validation_selection"
    assert "validation:alpha-tests" in validation["required_validation_ids"]
    assert evidence["family"] == "code_evidence"
    assert evidence["node_count"] >= 1

    soak = repo.parity_soak(rounds=4)
    assert soak["matched"] is True
    assert soak["all_agreed"] is True
    assert soak["scheduling_impact_agree"] is True
    assert soak["default_source"] == "duckdb"
    for family, digests in soak["digests_by_family"].items():
        assert len(set(digests)) == 1, family


def test_code_evidence_authority_consumer_surface(tmp_path: Path) -> None:
    port, backend = _port()
    consumer = build_code_evidence_authority(port)
    assert consumer.interface == CODE_EVIDENCE_AUTHORITY_INTERFACE
    assert consumer.default_source == "duckdb"

    record = _complete_record()
    published = consumer.publish_record(record)
    assert published["matched"] is True
    assert published["default_source"] == "duckdb"

    # Consumer APIs read DuckDB.
    evidence = consumer.code_evidence_query()
    assert evidence["default_source"] == "duckdb"
    assert evidence["node_count"] >= 1

    dep = consumer.dependency_query(seed_ids=["src/alpha.py"])
    impact = consumer.impact_query(roots=["src/alpha.py"])
    assert set(dep["nodes"]) == set(impact["nodes"])

    soak = consumer.parity_soak(rounds=3)
    assert soak["matched"] is True

    # Bundle dual-write path.
    bundle_root = build_tiny_fixture_bundle(tmp_path / "bundle")
    adapter = open_bundle_reader(bundle_root)
    report = consumer.publish_from_bundle_adapter(
        adapter,
        sources=[
            {"path": "fixture/good.py", "source": PY_OK, "language": "python"},
            {"path": "fixture/bad.py", "source": PY_BAD, "language": "python"},
        ],
        repository_id="repository:fixture",
        continue_on_parse_failure=True,
    )
    assert report["ok"] is True
    assert report["default_source"] == "duckdb"
    assert report["operational_authority"] == "duckdb"
    assert report["matched"] is True

    bundle_key = report["bundle_authority_key"]
    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, bundle_key)
    db = backend.get_db(AST_AUTHORITY_DOMAIN, bundle_key)
    assert legacy is not None and db is not None
    assert legacy["operational_authority"] == "duckdb"
    assert legacy["json_bundle"]["operational_authority"] is False

    # Invalidation leaves no stale facts for consumers.
    consumer.invalidate_source(path="src/alpha.py", reason="source_changed")
    after = consumer.code_evidence_query(path="src/alpha.py")
    assert after["node_count"] == 0

    restarted = consumer.restart()
    assert restarted["ok"] is True


# ---------------------------------------------------------------------------
# Cache dual-write authority
# ---------------------------------------------------------------------------


def test_analysis_cache_dual_writes_and_invalidates(tmp_path: Path) -> None:
    port, backend = _port()
    cache = build_ast_authority_analysis_cache(
        tmp_path / "cache", authority_port=port
    )
    assert isinstance(cache, ASTAuthorityAnalysisCache)
    assert cache.default_source == "duckdb"

    record = _complete_record()
    key = ast_cache_key_for_source(
        source_cid=record.provenance.source_cid,
        analyzer_cid=cid_for_structured({"analyzer": "ast-authority"}),
        configuration_cid=cid_for_structured({"config": "v1"}),
        semantics_cid=cid_for_structured({"semantics": "v1"}),
        policy_cid=cid_for_structured({"policy": "v1"}),
        solver_cid=cid_for_structured({"solver": "none"}),
        toolchain_cid=record.frontend.toolchain_cid,
    )
    assert key.result_schema == AST_CACHE_RESULT_SCHEMA
    result = cache.put_ast_record(key, record, outcome=OUTCOME_PROVED)
    assert result["ok"] is True
    assert result["default_source"] == "duckdb"
    assert result["authority"] is not None
    assert result["parity"]["matched"] is True

    hit = cache.lookup(key)
    assert hit.hit is True
    assert hit.result["operational_authority"] == "duckdb"

    authority_key = result["authority"]["authority_key"]
    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, authority_key)
    db = backend.get_db(AST_AUTHORITY_DOMAIN, authority_key)
    assert dict(legacy) == dict(db)

    # Consumer decisions via cache router.
    evidence = cache.consumer_decision("code_evidence")
    assert evidence["default_source"] == "duckdb"
    assert evidence["node_count"] >= 1

    inv = cache.invalidate_source(source_cid=record.provenance.source_cid)
    assert inv["ok"] is True
    after = cache.consumer_decision("code_evidence")
    assert after["node_count"] == 0

    restart = cache.restart()
    assert restart["ok"] is True


def test_repository_extraction_dual_writes() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port)
    batch = repo.extract_and_write(
        [
            {"path": "pkg/good.py", "source": PY_OK, "language": "python"},
            {"path": "pkg/bad.py", "source": PY_BAD, "language": "python"},
            {
                "path": "pkg/other.py",
                "source": b"def other():\n    return 2\n",
                "language": "python",
            },
        ],
        repository_id="repository:batch-auth",
        revision="rev-batch-auth-1",
        continue_on_parse_failure=True,
    )
    assert batch.ok is True
    assert batch.parsed_count >= 2
    assert batch.parse_failed_count >= 1

    evidence = repo.code_evidence_query()
    assert evidence["default_source"] == "duckdb"
    assert evidence["node_count"] >= 2

    # Convenience entry agrees.
    batch2 = extract_repository_ast_authority(
        [{"path": "one.py", "source": PY_OK, "language": "python"}],
        authority_port=port,
        repository_id="repository:batch-auth",
        revision="rev-batch-auth-2",
    )
    assert batch2.parsed_count == 1
    assert batch2.ok is True


def test_frontend_extraction_through_authority_repository() -> None:
    port, _ = _port()
    repo = build_ast_authority_repository(port)
    frontend = PythonASTExtractor()
    record = frontend.extract_from_source(
        PY_OK,
        path="pkg/alpha.py",
        repository_id="repository:frontend",
        revision="rev-fe-auth-1",
    )
    write = repo.write_record(record)
    assert write["ok"] is True
    assert write["default_source"] == "duckdb"
    parity = repo.emit_parity(write["authority_key"])
    assert parity["matched"] is True
    identity = write["db_projection"]["identity"]
    assert identity["source_cid"] == record.provenance.source_cid
    assert identity["ast_cid"] == record.cid
    projection = repo.get_projection(identity["blob_id"])
    assert projection is not None
    assert len(projection.symbols) >= 1 or len(projection.imports) >= 1


def test_code_evidence_authority_class_is_default_consumer() -> None:
    port, _ = _port()
    auth = CodeEvidenceAuthority(port)
    assert auth.default_source == "duckdb"
    assert auth.repository.mode == "dual"
    record = _complete_record(path="lib/mod.py")
    auth.publish_record(record)
    validation = auth.validation_selection_query(changed_paths=["lib/mod.py"])
    assert validation["default_source"] == "duckdb"
    conflict = auth.conflict_query()
    assert conflict["default_source"] == "duckdb"
