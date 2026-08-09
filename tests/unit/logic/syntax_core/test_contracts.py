"""Contract tests for syntax-core SourceDocument/Token/CST/Parse envelopes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.namespaces import (
    family_id,
    notation_id,
    profile_id,
    provider_id,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CONTRACTS_MODULE_VERSION,
    CSTNodeRole,
    DiagnosticSeverity,
    LOGIC_CST_INTERFACE,
    LOGIC_TOKEN_INTERFACE,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    PARSE_ARTIFACT_INTERFACE,
    PARSE_REQUEST_INTERFACE,
    ParseArtifact,
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SAFE_ENCODINGS,
    SOURCE_DOCUMENT_INTERFACE,
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
    assert_complete_coverage,
    content_sha256,
    normalize_encoding_name,
)


def _document(text: str = "P & Q", document_id: str = "doc:1") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _token(
    token_id: str,
    kind: str,
    lexeme: str,
    start: int,
    end: int,
    *,
    document_id: str = "doc:1",
) -> LogicToken:
    return LogicToken(
        token_id=token_id,
        kind=kind,
        lexeme=lexeme,
        range=SourceRange(start=start, end=end),
        document_id=document_id,
    )


def _covering_cst(document: SourceDocument, tokens: tuple[LogicToken, ...]) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind,
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if token.kind != TokenKind.EOF.value
    )
    # Fill any remaining hole with an explicit gap/recovery leaf so coverage is total.
    covered = [token.range for token in tokens if token.kind != TokenKind.EOF.value]
    holes: list[LogicCSTNode] = []
    cursor = 0
    for item in sorted(covered, key=lambda value: value.start):
        if item.start > cursor:
            holes.append(
                LogicCSTNode(
                    node_id=f"node:gap:{cursor}:{item.start}",
                    kind="gap",
                    range=SourceRange(start=cursor, end=item.start),
                    role=CSTNodeRole.GAP,
                )
            )
        cursor = max(cursor, item.end)
    if cursor < document.byte_length:
        holes.append(
            LogicCSTNode(
                node_id=f"node:gap:{cursor}:{document.byte_length}",
                kind="gap",
                range=SourceRange(start=cursor, end=document.byte_length),
                role=CSTNodeRole.GAP,
            )
        )
    leaves = tuple(sorted((*children, *holes), key=lambda node: node.range.start))
    root = LogicCSTNode(
        node_id="node:root",
        kind="source_file",
        range=document.full_range(),
        role=CSTNodeRole.ROOT,
        children=leaves,
    )
    return LogicCST(
        cst_id="cst:1",
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


# ---------------------------------------------------------------------------
# Happy path / interface identity
# ---------------------------------------------------------------------------


def test_module_version_and_safe_encodings() -> None:
    assert CONTRACTS_MODULE_VERSION == "1.0.0"
    assert SAFE_ENCODINGS == frozenset({"ascii", "utf-8"})


def test_source_document_round_trip_and_digest() -> None:
    document = _document("forall x. P(x)")
    assert document.interface == SOURCE_DOCUMENT_INTERFACE
    assert document.encoding == "utf-8"
    assert document.content_digest == content_sha256(document.content)
    assert document.line_index[0] == 0
    assert document.text == "forall x. P(x)"
    assert document.slice(SourceRange(0, 6)) == b"forall"

    restored = SourceDocument.from_dict(document.to_dict())
    assert restored == document
    assert restored.content == document.content


def test_source_document_ascii_encoding() -> None:
    document = SourceDocument.from_text("doc:ascii", "P", encoding="ascii")
    assert document.encoding == "ascii"
    assert document.content == b"P"


def test_token_cst_request_artifact_happy_path() -> None:
    document = _document("P&Q")
    tokens = (
        _token("tok:1", TokenKind.IDENTIFIER, "P", 0, 1),
        _token("tok:2", TokenKind.OPERATOR, "&", 1, 2),
        _token("tok:3", TokenKind.IDENTIFIER, "Q", 2, 3),
        _token("tok:eof", TokenKind.EOF, "", 3, 3),
    )
    cst = _covering_cst(document, tokens)
    assert cst.interface == LOGIC_CST_INTERFACE
    assert tokens[0].interface == LOGIC_TOKEN_INTERFACE

    request = ParseRequest(
        request_id="req:1",
        document=document,
        notation_id=notation_id("canonical_text"),
        profile_id=profile_id("classical"),
        family_id=family_id("propositional"),
        mode=ParseMode.STRICT,
        limits=ParseLimits(max_input_bytes=1024, max_tokens=128, max_depth=32),
    )
    assert request.interface == PARSE_REQUEST_INTERFACE
    assert request.notation_id.namespace.value == "notation"
    assert request.profile_id.namespace.value == "profile"

    surface = (
        SurfaceASTRef(
            node_id="ast:and",
            kind="binary_connective",
            range=SourceRange(0, 3),
            child_ids=("ast:p", "ast:q"),
        ),
        SurfaceASTRef(
            node_id="ast:p",
            kind="atom",
            range=SourceRange(0, 1),
        ),
        SurfaceASTRef(
            node_id="ast:q",
            kind="atom",
            range=SourceRange(2, 3),
        ),
    )
    artifact = ParseArtifact(
        artifact_id="art:1",
        request_id=request.request_id,
        document_id=document.document_id,
        status=ParseStatus.OK,
        tokens=tokens,
        cst=cst,
        surface_ast=surface,
        diagnostics=(),
    )
    assert artifact.interface == PARSE_ARTIFACT_INTERFACE
    artifact.validate_against(document, limits=request.limits)

    restored_request = ParseRequest.from_dict(request.to_dict())
    restored_artifact = ParseArtifact.from_dict(artifact.to_dict())
    assert restored_request.request_id == request.request_id
    assert restored_artifact.content_digest == artifact.content_digest
    assert restored_artifact.status is ParseStatus.OK


def test_records_are_immutable() -> None:
    document = _document()
    with pytest.raises(FrozenInstanceError):
        document.encoding = "ascii"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Invalid ranges
# ---------------------------------------------------------------------------


def test_invalid_range_end_before_start_fails() -> None:
    with pytest.raises(SyntaxContractError, match="invalid range"):
        SourceRange(start=4, end=2)


def test_invalid_character_range_fails() -> None:
    with pytest.raises(SyntaxContractError, match="character range"):
        SourceRange(start=0, end=1, start_char=5, end_char=1)


def test_range_beyond_source_fails() -> None:
    document = _document("ab")
    with pytest.raises(SyntaxContractError, match="exceeds source length"):
        SourceRange(0, 5).validate_against(document.byte_length)


def test_child_range_outside_parent_fails() -> None:
    with pytest.raises(SyntaxContractError, match="outside parent"):
        LogicCSTNode(
            node_id="node:parent",
            kind="group",
            range=SourceRange(0, 2),
            children=(
                LogicCSTNode(
                    node_id="node:child",
                    kind="atom",
                    range=SourceRange(0, 3),
                    role=CSTNodeRole.TOKEN,
                    token_id="tok:1",
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Unsafe encodings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "encoding",
    [
        "latin-1",
        "iso-8859-1",
        "cp1252",
        "utf-7",
        "utf-16",
        "utf-32",
        "idna",
        "unicode-escape",
    ],
)
def test_unsafe_encodings_fail_closed(encoding: str) -> None:
    with pytest.raises(SyntaxContractError, match="unsafe encoding|must be one of"):
        normalize_encoding_name(encoding)
    with pytest.raises(SyntaxContractError):
        SourceDocument(document_id="doc:bad", content=b"P", encoding=encoding)


def test_invalid_utf8_content_fails() -> None:
    with pytest.raises(SyntaxContractError, match="not valid utf-8"):
        SourceDocument(document_id="doc:bad", content=b"\xff\xfe", encoding="utf-8")


def test_nul_in_source_fails() -> None:
    with pytest.raises(SyntaxContractError, match="NUL"):
        SourceDocument(document_id="doc:nul", content=b"a\x00b", encoding="utf-8")


def test_mismatched_content_digest_fails() -> None:
    with pytest.raises(SyntaxContractError, match="content_digest"):
        SourceDocument(
            document_id="doc:1",
            content=b"P",
            encoding="utf-8",
            content_digest="0" * 64,
        )


# ---------------------------------------------------------------------------
# Missing source coverage
# ---------------------------------------------------------------------------


def test_missing_source_coverage_fails() -> None:
    document = _document("ABC")
    with pytest.raises(SyntaxContractError, match="uncovered hole|incomplete|hole"):
        LogicCST(
            cst_id="cst:hole",
            document_id=document.document_id,
            source_length=document.byte_length,
            root=LogicCSTNode(
                node_id="node:root",
                kind="source_file",
                range=document.full_range(),
                role=CSTNodeRole.ROOT,
                children=(
                    LogicCSTNode(
                        node_id="node:a",
                        kind="atom",
                        range=SourceRange(0, 1),
                        role=CSTNodeRole.TOKEN,
                        token_id="tok:a",
                    ),
                    # Missing coverage for bytes [1, 3)
                ),
            ),
        )


def test_assert_complete_coverage_detects_start_hole() -> None:
    with pytest.raises(SyntaxContractError, match="start of the source"):
        assert_complete_coverage((SourceRange(1, 3),), 3)


def test_root_must_span_entire_source() -> None:
    with pytest.raises(SyntaxContractError, match="entire source"):
        LogicCST(
            cst_id="cst:short",
            document_id="doc:1",
            source_length=3,
            root=LogicCSTNode(
                node_id="node:root",
                kind="source_file",
                range=SourceRange(0, 2),
                role=CSTNodeRole.ROOT,
            ),
        )


def test_coverage_with_recovery_gap_is_accepted() -> None:
    document = _document("A B")
    cst = LogicCST(
        cst_id="cst:gap",
        document_id=document.document_id,
        source_length=document.byte_length,
        root=LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=(
                LogicCSTNode(
                    node_id="node:a",
                    kind="atom",
                    range=SourceRange(0, 1),
                    role=CSTNodeRole.TOKEN,
                    token_id="tok:a",
                ),
                LogicCSTNode(
                    node_id="node:ws",
                    kind="whitespace",
                    range=SourceRange(1, 2),
                    role=CSTNodeRole.TRIVIA,
                ),
                LogicCSTNode(
                    node_id="node:b",
                    kind="atom",
                    range=SourceRange(2, 3),
                    role=CSTNodeRole.TOKEN,
                    token_id="tok:b",
                ),
            ),
        ),
    )
    assert cst.source_length == 3


# ---------------------------------------------------------------------------
# Unbounded limits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "max_input_bytes",
        "max_tokens",
        "max_depth",
        "max_diagnostics",
        "max_ambiguities",
        "max_time_ms",
        "max_memory_bytes",
    ],
)
def test_unbounded_or_non_positive_limits_fail(field_name: str) -> None:
    with pytest.raises(SyntaxContractError, match="positive finite bound|positive integer"):
        ParseLimits(**{field_name: 0})
    with pytest.raises(SyntaxContractError, match="positive finite bound|positive integer"):
        ParseLimits(**{field_name: -1})


def test_limit_above_hard_ceiling_fails() -> None:
    with pytest.raises(SyntaxContractError, match="hard ceiling"):
        ParseLimits(max_input_bytes=10_000_000_000)


def test_request_rejects_document_above_limits() -> None:
    document = _document("hello")
    with pytest.raises(SyntaxContractError, match="max_input_bytes"):
        ParseRequest(
            request_id="req:over",
            document=document,
            notation_id="canonical_text",
            profile_id="classical",
            limits=ParseLimits(max_input_bytes=1),
        )


# ---------------------------------------------------------------------------
# Duplicate diagnostics
# ---------------------------------------------------------------------------


def test_duplicate_diagnostic_ids_fail() -> None:
    document = _document("P")
    diagnostic = SyntaxDiagnostic(
        diagnostic_id="diag:1",
        code="syntax.parse.unexpected_token",
        message="unexpected token",
        severity=DiagnosticSeverity.ERROR,
        range=SourceRange(0, 1),
    )
    with pytest.raises(SyntaxContractError, match="duplicate diagnostics"):
        ParseArtifact(
            artifact_id="art:dup",
            request_id="req:1",
            document_id=document.document_id,
            status=ParseStatus.FAILED,
            diagnostics=(diagnostic, diagnostic),
        )


def test_related_diagnostic_must_exist() -> None:
    with pytest.raises(SyntaxContractError, match="unknown related diagnostics"):
        ParseArtifact(
            artifact_id="art:rel",
            request_id="req:1",
            document_id="doc:1",
            status=ParseStatus.FAILED,
            diagnostics=(
                SyntaxDiagnostic(
                    diagnostic_id="diag:1",
                    code="syntax.parse.error",
                    message="boom",
                    related_diagnostic_ids=("diag:missing",),
                ),
            ),
        )


def test_ok_status_rejects_error_diagnostics() -> None:
    document = _document("P")
    token = _token("tok:1", TokenKind.IDENTIFIER, "P", 0, 1)
    cst = _covering_cst(document, (token,))
    with pytest.raises(SyntaxContractError, match="status ok cannot carry"):
        ParseArtifact(
            artifact_id="art:bad-ok",
            request_id="req:1",
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=(token,),
            cst=cst,
            diagnostics=(
                SyntaxDiagnostic(
                    diagnostic_id="diag:err",
                    code="syntax.parse.error",
                    message="should not appear on ok",
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Wrong namespace / profile IDs
# ---------------------------------------------------------------------------


def test_wrong_namespace_for_profile_fails() -> None:
    document = _document("P")
    with pytest.raises(SyntaxContractError, match="namespace 'profile'"):
        ParseRequest(
            request_id="req:ns",
            document=document,
            notation_id=notation_id("canonical_text"),
            profile_id=provider_id("z3"),  # wrong namespace
        )


def test_wrong_namespace_for_notation_fails() -> None:
    document = _document("P")
    with pytest.raises(SyntaxContractError, match="namespace 'notation'"):
        ParseRequest(
            request_id="req:ns2",
            document=document,
            notation_id=family_id("first_order"),
            profile_id=profile_id("classical"),
        )


def test_wrong_namespace_for_family_fails() -> None:
    document = _document("P")
    with pytest.raises(SyntaxContractError, match="namespace 'family'"):
        ParseRequest(
            request_id="req:ns3",
            document=document,
            notation_id="canonical_text",
            profile_id="classical",
            family_id=profile_id("classical"),
        )


def test_invalid_identifier_string_fails() -> None:
    document = _document("P")
    with pytest.raises(SyntaxContractError):
        ParseRequest(
            request_id="req:bad-id",
            document=document,
            notation_id="Not A Valid Id!!!",
            profile_id="classical",
        )


# ---------------------------------------------------------------------------
# Additional structural contracts
# ---------------------------------------------------------------------------


def test_source_map_unique_entries_and_bounds() -> None:
    document = _document("abcd")
    source_map = SourceMap(
        map_id="map:1",
        document_id=document.document_id,
        entries=(
            SourceMapEntry(
                entry_id="entry:1",
                range=SourceRange(0, 2),
                role="span",
            ),
            SourceMapEntry(
                entry_id="entry:2",
                range=SourceRange(2, 4),
                role="span",
            ),
        ),
    )
    request = ParseRequest(
        request_id="req:map",
        document=document,
        notation_id="canonical_text",
        profile_id="classical",
        source_map=source_map,
    )
    assert len(request.source_map.entries) == 2

    with pytest.raises(SyntaxContractError, match="unique entry_id"):
        SourceMap(
            map_id="map:dup",
            document_id=document.document_id,
            entries=(
                SourceMapEntry(entry_id="entry:1", range=SourceRange(0, 1)),
                SourceMapEntry(entry_id="entry:1", range=SourceRange(1, 2)),
            ),
        )


def test_duplicate_token_ids_fail() -> None:
    document = _document("PP")
    token = _token("tok:same", TokenKind.IDENTIFIER, "P", 0, 1)
    token2 = _token("tok:same", TokenKind.IDENTIFIER, "P", 1, 2)
    with pytest.raises(SyntaxContractError, match="unique token_id"):
        ParseArtifact(
            artifact_id="art:tok",
            request_id="req:1",
            document_id=document.document_id,
            status=ParseStatus.FAILED,
            tokens=(token, token2),
        )


def test_surface_ast_unknown_child_fails() -> None:
    with pytest.raises(SyntaxContractError, match="unknown child ids"):
        ParseArtifact(
            artifact_id="art:ast",
            request_id="req:1",
            document_id="doc:1",
            status=ParseStatus.FAILED,
            surface_ast=(
                SurfaceASTRef(
                    node_id="ast:1",
                    kind="app",
                    range=SourceRange(0, 1),
                    child_ids=("ast:missing",),
                ),
            ),
        )


def test_recovered_status_requires_cst() -> None:
    with pytest.raises(SyntaxContractError, match="recovered requires a LogicCST"):
        ParseArtifact(
            artifact_id="art:rec",
            request_id="req:1",
            document_id="doc:1",
            status=ParseStatus.RECOVERED,
        )


def test_bare_string_ids_coerce_to_expected_namespace() -> None:
    document = _document("P")
    request = ParseRequest(
        request_id="req:coerce",
        document=document,
        notation_id="smt_lib2",
        profile_id="qf_bv",
        family_id="first_order",
    )
    assert request.notation_id.qualified == "notation:smt_lib2"
    assert request.profile_id.qualified == "profile:qf_bv"
    assert request.family_id.qualified == "family:first_order"


def test_validate_against_enforces_limits_and_ranges() -> None:
    document = _document("PQ")
    tokens = (
        _token("tok:1", TokenKind.IDENTIFIER, "P", 0, 1),
        _token("tok:2", TokenKind.IDENTIFIER, "Q", 1, 2),
    )
    cst = _covering_cst(document, tokens)
    artifact = ParseArtifact(
        artifact_id="art:val",
        request_id="req:1",
        document_id=document.document_id,
        status=ParseStatus.OK,
        tokens=tokens,
        cst=cst,
    )
    artifact.validate_against(document, limits=ParseLimits(max_tokens=8, max_diagnostics=4))
    with pytest.raises(SyntaxContractError, match="token count exceeds"):
        artifact.validate_against(document, limits=ParseLimits(max_tokens=1))
