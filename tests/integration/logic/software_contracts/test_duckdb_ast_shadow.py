"""Integration tests for AST / code-evidence authority shadow writers (DQK-068).

Acceptance coverage:

* JSON bundle and DB projections have differential parity
* Source / hash / span / CID identity is exact
* Python and TypeScript parse failures remain durable without blocking
  unrelated files

Producers under test:

* repository extraction (``ASTAuthorityShadowWriter``)
* software-contract analysis cache (``ASTShadowAnalysisCache``)
* contract registry (``shadow_publish_registry``)
* code-evidence consumers (``CodeEvidenceAuthorityShadow``)
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

    The DuckDB-quack sealed validator only ships pytest + duckdb.  Software-
    contract CID helpers lazily import ``multiformats``; under that hermetic
    toolchain the dependency is unavailable.  This shim implements the exact
    CIDv1 / base32 / sha2-256 surface used by ``content.cid_for_*`` so
    source/hash/span/CID identity assertions remain exact without widening the
    validator wheel cache.
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
            # multihash layout: code | length | digest-bytes
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
    root.cid = cid_mod  # type: ignore[attr-defined]
    sys.modules["multiformats"] = root
    sys.modules["multiformats.multihash"] = mh
    sys.modules["multiformats.cid"] = cid_mod


_ensure_multiformats_for_sealed_validator()

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    MemoryAuthorityBackend,
    build_authority_port,
)
from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
    CodeEvidenceAuthorityShadow,
    build_code_evidence_authority_shadow,
    build_tiny_fixture_bundle,
    open_bundle_reader,
)
from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
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
)
from ipfs_datasets_py.logic.software_contracts.cache import (
    AST_CACHE_RESULT_SCHEMA,
    ASTShadowAnalysisCache,
    AnalysisCacheKey,
    OUTCOME_PROVED,
    ast_cache_key_for_source,
    build_ast_shadow_analysis_cache,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    BoundedPredicate,
    CallableContract,
    ContractAuthority,
    ContractProvenance,
    DataContract,
    EffectContract,
    ParameterContract,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    PARSE_FAILURE_DIAGNOSTIC_CODE,
    ParseStatus,
    build_duckdb_ast_store,
    project_ast_record,
    project_parse_failure,
    spans_survive_projection,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)
from ipfs_datasets_py.logic.software_contracts.registry import (
    ContractRegistry,
    registry_evidence_edges,
    shadow_publish_registry,
)
from ipfs_datasets_py.logic.software_contracts.repository import (
    AST_AUTHORITY_DOMAIN,
    AST_SHADOW_OWNER_TASK,
    ASTAuthorityShadowWriter,
    authority_key_for_projection,
    build_ast_authority_shadow_writer,
    differential_parity,
    evidence_edges_from_projection,
    extract_repository_ast_shadow,
    json_bundle_from_projection,
    projection_to_authority_payload,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PY_OK = b"from os import path\n\ndef alpha(value: int) -> int:\n    return path.join(str(value))\n"
PY_BAD = b"def broken(\n"  # syntax error
TS_OK = b"export function beta(x: number): number { return x + 1; }\n"
TS_BAD = b"export function broken( { return 1; }\n"  # syntax error


def _port(mode: AuthorityMode = AuthorityMode.SHADOW):
    store = MemoryAuthorityBackend()
    port = build_authority_port(
        store,
        domain=AST_AUTHORITY_DOMAIN,
        initial_mode=mode,
        writer_id="writer:test-ast-shadow",
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


def _complete_record(source: bytes = PY_OK, path: str = "src/alpha.py") -> ASTRecord:
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
            repository_id="repository:shadow-test",
            revision="rev-shadow-1",
            repository_tree_cid=cid_for_structured({"git_tree": "tree-shadow"}),
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


def _sample_contract() -> CallableContract:
    authority = ContractAuthority(
        authority_id="authority:registry:v1",
        rank="reviewed_registry",
        owner="ipfs_datasets_py",
        revision="1.0.0",
        policy_ref="policy:cross-package-contracts-v1",
        source_cid=None,
    )
    prov = ContractProvenance(
        fact_kind="declared",
        authority=authority,
        source_path="docs/schemas/software-contract-v1.schema.json",
        source_symbol="alpha",
        note="",
    )
    return CallableContract(
        contract_id="contract:alpha:v1",
        qualified_name="pkg.alpha",
        owner_module="pkg",
        shape="sync_function",
        provenance=prov,
        visibility="public",
        parameters=(
            ParameterContract(
                name="value",
                kind="positional_or_named",
                position=0,
                data=DataContract(
                    data_id="data:value",
                    name="value",
                    type_name="int",
                    provenance=prov,
                    nullable=False,
                ),
                default_present=False,
            ),
        ),
        return_data=DataContract(
            data_id="data:return",
            name="return",
            type_name="int",
            provenance=prov,
            nullable=False,
        ),
        preconditions=(
            BoundedPredicate(
                predicate_id="pred:pre:value-not-null",
                role="precondition",
                operator="is_not_null",
                subject="value",
                provenance=prov,
            ),
        ),
        postconditions=(),
        invariants=(),
        assumptions=(),
        effects=(
            EffectContract(
                effect_id="effect:filesystem:read",
                kind="filesystem",
                operation="read",
                provenance=prov,
                subject="return",
                permitted=True,
                required=False,
            ),
        ),
        exceptions=(),
        resources=(),
        capabilities=(),
    )


# ---------------------------------------------------------------------------
# Projection identity / differential parity
# ---------------------------------------------------------------------------


def test_projection_payload_preserves_source_hash_span_and_cid_identity() -> None:
    record = _complete_record()
    projection = project_ast_record(record)
    assert spans_survive_projection(record, projection)
    payload = projection_to_authority_payload(projection)
    identity = payload["identity"]
    assert identity["source_cid"] == record.provenance.source_cid
    assert identity["ast_cid"] == record.cid
    assert identity["blob_id"] == projection.blob_id
    assert identity["path"] == "src/alpha.py"
    assert identity["revision"] == "rev-shadow-1"
    assert identity["parse_status"] == ParseStatus.OK.value

    # Exact span identity on symbols / imports / calls / effects.
    symbol = payload["symbols"][0]
    assert symbol["start_byte"] == record.symbols[0].span.start_byte
    assert symbol["end_byte"] == record.symbols[0].span.end_byte
    assert symbol["start_line"] == record.symbols[0].span.start_line
    assert symbol["qualified_name"] == "alpha.alpha"
    assert payload["imports"][0]["module"] == "os"
    assert payload["calls"][0]["callee_name"] == "path.join"
    assert payload["effects"][0]["kind"] == "io"
    assert payload["diagnostics"][0]["code"] == "frontend.note"

    bundle = json_bundle_from_projection(projection)
    report = differential_parity(bundle, payload)
    assert report["matched"] is True
    assert report["identity_mismatches"] == []
    assert report["family_mismatches"] == []
    assert report["counts_match"] is True


def test_shadow_write_json_and_db_have_differential_parity() -> None:
    port, backend = _port()
    writer = build_ast_authority_shadow_writer(port)
    record = _complete_record()
    projection = project_ast_record(record)
    write = writer.write_projection(projection)
    assert write["ok"] is True
    assert write["authority"] == "legacy"

    key = write["authority_key"]
    assert key == authority_key_for_projection(projection)
    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, key)
    db = backend.get_db(AST_AUTHORITY_DOMAIN, key)
    assert legacy is not None and db is not None
    assert legacy["kind"] == "ast_shadow_dual"
    assert dict(legacy) == dict(db)

    parity = writer.emit_parity(key)
    assert parity["matched"] is True
    assert parity["port_parity_matched"] is True
    assert parity["differential"]["matched"] is True
    assert parity["dual_identity_match"] is True

    # Evidence edges also land on both surfaces.
    edges = evidence_edges_from_projection(projection)
    assert edges
    assert any(edge["kind"] == "defines_symbol" for edge in edges)
    for edge in edges:
        edge_key = f"evidence:{edge['edge_id']}"
        assert backend.get_legacy(AST_AUTHORITY_DOMAIN, edge_key) is not None
        assert backend.get_db(AST_AUTHORITY_DOMAIN, edge_key) is not None


# ---------------------------------------------------------------------------
# Repository extraction: multi-file batch, durable parse failures
# ---------------------------------------------------------------------------


def test_repository_extraction_shadows_python_and_survives_parse_failures() -> None:
    port, backend = _port()
    writer = ASTAuthorityShadowWriter(port)

    sources = [
        {"path": "pkg/good.py", "source": PY_OK, "language": "python"},
        {"path": "pkg/bad.py", "source": PY_BAD, "language": "python"},
        {"path": "pkg/other.py", "source": b"def other():\n    return 2\n", "language": "python"},
        {"path": "pkg/readme.md", "source": b"# not code\n", "language": "markdown"},
    ]
    batch = writer.extract_and_shadow(
        sources,
        repository_id="repository:batch",
        revision="rev-batch-1",
        continue_on_parse_failure=True,
    )
    assert batch.ok is True
    assert batch.parsed_count >= 2
    assert batch.parse_failed_count >= 1
    assert batch.skipped_count >= 1
    assert batch.durable_parse_failures >= 1

    statuses = {item.path: item.status for item in batch.results}
    assert statuses["pkg/good.py"] == "parsed"
    assert statuses["pkg/bad.py"] == "parse_failed"
    assert statuses["pkg/other.py"] == "parsed"
    assert statuses["pkg/readme.md"] == "skipped"

    # Failure did not block the later good file.
    bad = next(item for item in batch.results if item.path == "pkg/bad.py")
    other = next(item for item in batch.results if item.path == "pkg/other.py")
    assert bad.blocked_unrelated is False
    assert other.blocked_unrelated is False
    assert other.status == "parsed"
    assert other.authority_key is not None

    # Parse failure is durable and queryable from the store.
    failures = writer.store.query_parse_failures()
    assert failures
    assert any(item.is_parse_failure for item in failures)
    assert any(
        item.code == PARSE_FAILURE_DIAGNOSTIC_CODE
        or "parse" in item.code
        or item.is_parse_failure
        for item in failures
    )

    # All written keys have port + differential parity.
    for report in batch.parity_reports:
        assert report["matched"] is True, report

    # Convenience entry point agrees.
    batch2 = extract_repository_ast_shadow(
        [{"path": "one.py", "source": PY_OK, "language": "python"}],
        authority_port=port,
        repository_id="repository:batch",
        revision="rev-batch-2",
    )
    assert batch2.parsed_count == 1
    assert batch2.ok is True


def test_typescript_parse_failure_is_durable_and_non_blocking() -> None:
    port, _ = _port()
    writer = build_ast_authority_shadow_writer(port)

    # Force TS path: good python after bad typescript proves non-blocking.
    sources = [
        {"path": "ui/broken.ts", "source": TS_BAD, "language": "typescript"},
        {"path": "svc/ok.py", "source": PY_OK, "language": "python"},
    ]
    batch = writer.extract_and_shadow(
        sources,
        repository_id="repository:ts",
        revision="rev-ts-1",
        # No TypeScriptFrontend — exercise durable failure path.
        typescript_frontend=None,
        continue_on_parse_failure=True,
    )
    assert batch.ok is True
    by_path = {item.path: item for item in batch.results}
    assert by_path["ui/broken.ts"].status == "parse_failed"
    assert by_path["svc/ok.py"].status == "parsed"
    assert by_path["ui/broken.ts"].blocked_unrelated is False
    assert by_path["svc/ok.py"].authority_key is not None

    # Durable failure projection is in the store and authority port.
    failures = writer.store.query_parse_failures()
    assert failures
    key = by_path["ui/broken.ts"].authority_key
    assert key is not None
    parity = writer.emit_parity(key)
    assert parity["matched"] is True


# ---------------------------------------------------------------------------
# Cache shadow
# ---------------------------------------------------------------------------


def test_analysis_cache_shadows_ast_projections(tmp_path: Path) -> None:
    port, backend = _port()
    cache = build_ast_shadow_analysis_cache(tmp_path / "cache", authority_port=port)
    record = _complete_record()
    key = ast_cache_key_for_source(
        source_cid=record.provenance.source_cid,
        analyzer_cid=cid_for_structured({"analyzer": "ast-shadow"}),
        configuration_cid=cid_for_structured({"config": "v1"}),
        semantics_cid=cid_for_structured({"semantics": "v1"}),
        policy_cid=cid_for_structured({"policy": "v1"}),
        solver_cid=cid_for_structured({"solver": "none"}),
        toolchain_cid=record.frontend.toolchain_cid,
    )
    assert key.result_schema == AST_CACHE_RESULT_SCHEMA
    result = cache.put_ast_record(key, record, outcome=OUTCOME_PROVED)
    assert result["ok"] is True
    assert result["cache_receipt_cid"]
    assert result["shadow"] is not None
    assert result["parity"]["matched"] is True
    assert result["identity"]["source_cid"] == record.provenance.source_cid
    assert result["identity"]["ast_cid"] == record.cid

    # Cache hit returns the AST projection payload.
    hit = cache.lookup(key)
    assert hit.hit is True
    assert hit.result["schema"] == AST_CACHE_RESULT_SCHEMA
    assert hit.result["identity"]["ast_cid"] == record.cid

    # Authority port holds dual JSON/DB documents with parity.
    authority_key = result["shadow"]["authority_key"]
    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, authority_key)
    db = backend.get_db(AST_AUTHORITY_DOMAIN, authority_key)
    assert dict(legacy) == dict(db)

    # Parse-failure path is also cacheable + shadowable.
    fail_key = ast_cache_key_for_source(
        source_cid=cid_for_bytes(PY_BAD),
        analyzer_cid=cid_for_structured({"analyzer": "ast-shadow"}),
        configuration_cid=cid_for_structured({"config": "v1"}),
        semantics_cid=cid_for_structured({"semantics": "v1"}),
        policy_cid=cid_for_structured({"policy": "v1"}),
        solver_cid=cid_for_structured({"solver": "none"}),
        toolchain_cid=record.frontend.toolchain_cid,
    )
    fail = cache.put_parse_failure(
        fail_key,
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(PY_BAD),
            path="pkg/bad.py",
            repository_id="repository:shadow-test",
            revision="rev-shadow-1",
        ),
        language="python",
        message="syntax error",
        frontend_name="cpython-ast",
        frontend_version="3.12",
    )
    assert fail["ok"] is True
    assert fail["parity"]["matched"] is True
    assert fail["identity"]["parse_status"] == ParseStatus.FAILED.value


# ---------------------------------------------------------------------------
# Registry shadow
# ---------------------------------------------------------------------------


def test_registry_shadow_publishes_evidence_edges() -> None:
    port, backend = _port()
    contract = _sample_contract()
    registry = ContractRegistry.from_callables(
        "registry:shadow-test",
        [contract],
        revision="1.0.0",
    )
    edges = registry_evidence_edges(registry)
    assert edges
    assert any(edge["kind"] == "defines_symbol" for edge in edges)
    assert any(edge["kind"] == "derived_from" for edge in edges)

    published = shadow_publish_registry(registry, port)
    assert published["ok"] is True
    assert published["matched"] is True
    assert published["parity_matched"] is True
    assert published["differential_identity_match"] is True
    assert published["evidence_edge_count"] == len(edges)

    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, published["authority_key"])
    db = backend.get_db(AST_AUTHORITY_DOMAIN, published["authority_key"])
    assert dict(legacy["json_bundle"]) == dict(db["db_projection"])
    assert legacy["identity"]["registry_cid"] == registry.cid


# ---------------------------------------------------------------------------
# Code-evidence consumer shadow
# ---------------------------------------------------------------------------


def test_code_evidence_consumer_shadows_projections_and_bundle(tmp_path: Path) -> None:
    port, backend = _port()
    shadow = build_code_evidence_authority_shadow(port)
    assert shadow.interface.startswith("CodeEvidenceAuthorityShadow")

    # Direct projection publish with exact identity parity.
    record = _complete_record()
    projection = project_ast_record(record)
    published = shadow.publish_projection(projection)
    assert published["matched"] is True
    assert published["parity"]["matched"] is True
    key = published["authority_key"]
    diff = shadow.differential_parity_for_key(key)
    assert diff["matched"] is True
    assert diff["identity_mismatches"] == []

    # Bundle adapter path: fixture JSON + extracted sources.
    bundle_root = build_tiny_fixture_bundle(tmp_path / "bundle")
    adapter = open_bundle_reader(bundle_root)
    report = shadow.publish_from_bundle_adapter(
        adapter,
        sources=[
            {"path": "fixture/good.py", "source": PY_OK, "language": "python"},
            {"path": "fixture/bad.py", "source": PY_BAD, "language": "python"},
        ],
        repository_id="repository:fixture",
        continue_on_parse_failure=True,
    )
    assert report["ok"] is True
    assert report["matched"] is True
    assert report["differential_match"] is True
    assert report["edge_write_count"] >= 1
    assert report["batch"] is not None
    assert report["batch"]["parse_failed_count"] >= 1
    assert report["batch"]["parsed_count"] >= 1

    bundle_key = report["bundle_authority_key"]
    legacy = backend.get_legacy(AST_AUTHORITY_DOMAIN, bundle_key)
    db = backend.get_db(AST_AUTHORITY_DOMAIN, bundle_key)
    assert dict(legacy["json_bundle"]) == dict(db["db_projection"])
    assert legacy["identity"]["revision"] == adapter.revision

    # Durable parse failure for TS without blocking further work.
    fail = shadow.publish_parse_failure(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(TS_BAD),
            path="ui/broken.ts",
            repository_id="repository:fixture",
            revision=adapter.revision,
        ),
        language="typescript",
        message="unexpected token",
        frontend_name="typescript-compiler-api",
        frontend_version="5.6.3",
    )
    assert fail["matched"] is True
    failures = shadow.writer.store.query_parse_failures()
    assert any(item.is_parse_failure for item in failures)


def test_owner_task_and_domain_pins() -> None:
    assert AST_SHADOW_OWNER_TASK == "DQK-068"
    assert AST_AUTHORITY_DOMAIN == "asts"
    port, _ = _port()
    writer = build_ast_authority_shadow_writer(port)
    assert writer.domain == AST_AUTHORITY_DOMAIN
    assert writer.interface == "ASTAuthorityShadowWriter@1"
    shadow = CodeEvidenceAuthorityShadow(port)
    assert shadow.port.domain == AST_AUTHORITY_DOMAIN


def test_frontend_extraction_identity_matches_projection_spans() -> None:
    """End-to-end: Python frontend → projection → authority shadow parity."""

    port, _ = _port()
    writer = build_ast_authority_shadow_writer(port)
    frontend = PythonASTExtractor()
    record = frontend.extract_from_source(
        PY_OK,
        path="pkg/alpha.py",
        repository_id="repository:frontend",
        revision="rev-fe-1",
    )
    write = writer.write_record(record)
    assert write["ok"] is True
    parity = writer.emit_parity(write["authority_key"])
    assert parity["matched"] is True
    identity = write["db_projection"]["identity"]
    assert identity["source_cid"] == record.provenance.source_cid
    assert identity["ast_cid"] == record.cid
    projection = writer.store.get(identity["blob_id"])
    assert projection is not None
    assert spans_survive_projection(record, projection)
    # Symbols / imports / calls present when frontend extracts them.
    assert len(projection.symbols) >= 1 or len(projection.imports) >= 1
