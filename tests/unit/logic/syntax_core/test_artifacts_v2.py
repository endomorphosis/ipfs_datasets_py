"""Unit tests for versioned parse/elaboration artifacts (LFP2-006).

Acceptance coverage:

* parse and elaboration artifacts preserve exact source and diagnostic lineage
* v2 artifacts round-trip through codecs
* legacy ParseArtifact@1 lifts into ParseArtifact@2 via explicit adapters
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ARTIFACTS_V2_MODULE_VERSION,
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    ArtifactLineageError,
    ArtifactV2Error,
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.ast import mk_predicate
from ipfs_datasets_py.logic.syntax_core.codec import (
    CodecKind,
    TypedLogicCodec,
    round_trip,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseArtifact,
    ParseStatus,
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.elaboration import (
    ElaborationStatus,
    LogicElaborator,
)
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


def _document(text: str = "P", document_id: str = "doc:art-v2") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _token(
    token_id: str,
    kind: str,
    lexeme: str,
    start: int,
    end: int,
    *,
    document_id: str = "doc:art-v2",
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
        cst_id="cst:art-v2",
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _ok_parse_artifact(
    document: SourceDocument | None = None,
    *,
    with_root: bool = True,
) -> ParseArtifactV2:
    document = document or _document()
    tokens = (
        _token("tok:p", "identifier", "P", 0, 1, document_id=document.document_id),
        _token(
            "tok:eof",
            TokenKind.EOF.value,
            "",
            document.byte_length,
            document.byte_length,
            document_id=document.document_id,
        ),
    )
    cst = _covering_cst(document, tokens)
    typed_roots = (mk_predicate("n:p", "P"),) if with_root else ()
    source_map = SourceMap(
        map_id="map:1",
        document_id=document.document_id,
        entries=(
            SourceMapEntry(
                entry_id="map:entry:p",
                range=SourceRange(start=0, end=1),
                role="identifier",
            ),
        ),
    )
    return ParseArtifactV2.from_document(
        document,
        artifact_id="art:parse:1",
        request_id="req:1",
        status=ParseStatus.OK,
        tokens=tokens,
        cst=cst,
        typed_roots=typed_roots,
        source_map=source_map,
    )


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert PARSE_ARTIFACT_V2_INTERFACE == "ParseArtifact@2"
    assert ELABORATION_ARTIFACT_V2_INTERFACE == "ElaborationArtifact@2"
    assert ARTIFACTS_V2_MODULE_VERSION


# ---------------------------------------------------------------------------
# ParseArtifact@2
# ---------------------------------------------------------------------------


def test_parse_artifact_binds_source_digest() -> None:
    document = _document("P & Q")
    artifact = _ok_parse_artifact(document)
    assert artifact.interface == PARSE_ARTIFACT_V2_INTERFACE
    assert artifact.source_digest == document.content_digest
    assert artifact.content_digest
    assert artifact.lineage_digest
    assert artifact.content_digest != artifact.lineage_digest
    artifact.validate_against(document)


def test_parse_artifact_rejects_source_digest_mismatch() -> None:
    document = _document("P")
    other = _document("Q", document_id="doc:art-v2")
    artifact = _ok_parse_artifact(document)
    with pytest.raises(ArtifactLineageError, match="source_digest"):
        artifact.validate_against(other)


def test_parse_artifact_preserves_diagnostic_lineage() -> None:
    document = _document("P")
    parent = SyntaxDiagnostic(
        diagnostic_id="diag:parse:parent",
        code="parse.warning.sample",
        message="parent warning",
        severity=DiagnosticSeverity.WARNING,
        range=SourceRange(start=0, end=1),
    )
    child = SyntaxDiagnostic(
        diagnostic_id="diag:parse:child",
        code="parse.warning.related",
        message="related warning",
        severity=DiagnosticSeverity.WARNING,
        range=SourceRange(start=0, end=1),
        related_diagnostic_ids=("diag:parse:parent",),
    )
    tokens = (
        _token("tok:p", "identifier", "P", 0, 1),
        _token("tok:eof", TokenKind.EOF.value, "", 1, 1),
    )
    artifact = ParseArtifactV2.from_document(
        document,
        artifact_id="art:parse:diag",
        request_id="req:diag",
        status=ParseStatus.RECOVERED,
        tokens=tokens,
        cst=_covering_cst(document, tokens),
        diagnostics=(parent, child),
    )
    assert len(artifact.diagnostics) == 2
    assert artifact.diagnostics[1].related_diagnostic_ids == ("diag:parse:parent",)
    restored = ParseArtifactV2.from_dict(artifact.to_dict())
    assert restored.lineage_digest == artifact.lineage_digest
    assert restored.diagnostics[1].related_diagnostic_ids == ("diag:parse:parent",)


def test_parse_artifact_rejects_dangling_related_diagnostic() -> None:
    document = _document("P")
    tokens = (
        _token("tok:p", "identifier", "P", 0, 1),
        _token("tok:eof", TokenKind.EOF.value, "", 1, 1),
    )
    with pytest.raises(ArtifactLineageError, match="unknown related"):
        ParseArtifactV2.from_document(
            document,
            artifact_id="art:parse:bad-diag",
            request_id="req:bad",
            status=ParseStatus.FAILED,
            tokens=tokens,
            diagnostics=(
                SyntaxDiagnostic(
                    diagnostic_id="diag:orphan",
                    code="parse.error.sample",
                    message="orphan",
                    related_diagnostic_ids=("diag:missing",),
                ),
            ),
        )


def test_parse_artifact_from_v1_adapter() -> None:
    document = _document("P")
    tokens = (
        _token("tok:p", "identifier", "P", 0, 1),
        _token("tok:eof", TokenKind.EOF.value, "", 1, 1),
    )
    v1 = ParseArtifact(
        artifact_id="art:v1",
        request_id="req:v1",
        document_id=document.document_id,
        status=ParseStatus.OK,
        tokens=tokens,
        cst=_covering_cst(document, tokens),
    )
    v2 = ParseArtifactV2.from_v1(
        v1,
        source_digest=document.content_digest,
        typed_roots=(mk_predicate("n:p", "P"),),
    )
    assert v2.legacy_content_digest == v1.content_digest
    assert v2.source_digest == document.content_digest
    assert len(v2.typed_roots) == 1
    projected = v2.to_v1()
    assert projected.interface == "ParseArtifact@1"
    assert projected.document_id == document.document_id


def test_parse_artifact_content_digest_is_stable() -> None:
    document = _document("P")
    a = _ok_parse_artifact(document)
    b = ParseArtifactV2.from_dict(a.to_dict())
    assert a.content_digest == b.content_digest
    assert a.lineage_digest == b.lineage_digest


def test_parse_artifact_rejects_wrong_content_digest() -> None:
    document = _document("P")
    artifact = _ok_parse_artifact(document)
    payload = artifact.to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(ArtifactV2Error, match="content_digest"):
        ParseArtifactV2.from_dict(payload)


# ---------------------------------------------------------------------------
# ElaborationArtifact@2
# ---------------------------------------------------------------------------


def test_elaboration_artifact_binds_parse_and_source_lineage() -> None:
    document = _document("P")
    parse = _ok_parse_artifact(document)
    root = mk_predicate("n:p", "P")
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P",)))
    result = elaborator.elaborate(root, expression_id="expr:p")
    artifact = ElaborationArtifactV2.from_elaboration_result(
        result,
        artifact_id="art:elab:1",
        parse_artifact=parse,
        document=document,
    )
    assert artifact.interface == ELABORATION_ARTIFACT_V2_INTERFACE
    assert artifact.status is ElaborationArtifactStatus.OK
    assert artifact.backend_ready is True
    assert artifact.parse_artifact_id == parse.artifact_id
    assert artifact.source_digest == document.content_digest
    assert artifact.parse_content_digest == parse.content_digest
    assert artifact.parse_lineage_digest == parse.lineage_digest
    artifact.validate_lineage(parse_artifact=parse, document=document)


def test_elaboration_artifact_merges_parse_diagnostic_lineage() -> None:
    document = _document("P")
    tokens = (
        _token("tok:p", "identifier", "P", 0, 1),
        _token("tok:eof", TokenKind.EOF.value, "", 1, 1),
    )
    parse_diag = SyntaxDiagnostic(
        diagnostic_id="diag:parse:warn",
        code="parse.warning.sample",
        message="recovered whitespace",
        severity=DiagnosticSeverity.WARNING,
        range=SourceRange(start=0, end=1),
    )
    parse = ParseArtifactV2.from_document(
        document,
        artifact_id="art:parse:warn",
        request_id="req:warn",
        status=ParseStatus.RECOVERED,
        tokens=tokens,
        cst=_covering_cst(document, tokens),
        diagnostics=(parse_diag,),
        typed_roots=(mk_predicate("n:p", "P"),),
    )
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P",)))
    result = elaborator.elaborate(mk_predicate("n:p", "P"), expression_id="expr:p")
    artifact = ElaborationArtifactV2.from_elaboration_result(
        result,
        artifact_id="art:elab:warn",
        parse_artifact=parse,
    )
    ids = {item.diagnostic_id for item in artifact.diagnostics}
    assert "diag:parse:warn" in ids
    restored = ElaborationArtifactV2.from_dict(artifact.to_dict())
    assert restored.lineage_digest == artifact.lineage_digest
    assert "diag:parse:warn" in {
        item.diagnostic_id for item in restored.diagnostics
    }


def test_elaboration_artifact_lineage_mismatch_fails() -> None:
    document = _document("P")
    parse = _ok_parse_artifact(document)
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P",)))
    result = elaborator.elaborate(mk_predicate("n:p", "P"))
    artifact = ElaborationArtifactV2.from_elaboration_result(
        result,
        artifact_id="art:elab:2",
        parse_artifact=parse,
    )
    other_doc = _document("Q", document_id="doc:other")
    with pytest.raises(ArtifactLineageError, match="document_id"):
        artifact.validate_lineage(document=other_doc)


def test_elaboration_artifact_failed_not_backend_ready() -> None:
    document = _document("P")
    parse = _ok_parse_artifact(document)
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P", "Q")))
    # Unknown symbol relative to a signature that only has P,Q — use R.
    result = elaborator.elaborate(mk_predicate("n:r", "R"), expression_id="expr:r")
    assert result.status is not ElaborationStatus.OK
    artifact = ElaborationArtifactV2.from_elaboration_result(
        result,
        artifact_id="art:elab:fail",
        parse_artifact=parse,
    )
    assert artifact.backend_ready is False
    with pytest.raises(ArtifactV2Error, match="not backend-ready"):
        artifact.require_backend_ready()


def test_elaborator_elaborate_artifact_helper() -> None:
    document = _document("P")
    parse = _ok_parse_artifact(document)
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P",)))
    artifact = elaborator.elaborate_artifact(
        mk_predicate("n:p", "P"),
        parse_artifact=parse,
        artifact_id="art:elab:helper",
        expression_id="expr:helper",
    )
    assert isinstance(artifact, ElaborationArtifactV2)
    assert artifact.backend_ready is True
    assert artifact.parse_lineage_digest == parse.lineage_digest


def test_elaboration_artifact_to_result_projection() -> None:
    document = _document("P")
    parse = _ok_parse_artifact(document)
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P",)))
    result = elaborator.elaborate(mk_predicate("n:p", "P"), expression_id="expr:p")
    artifact = ElaborationArtifactV2.from_elaboration_result(
        result,
        artifact_id="art:elab:proj",
        parse_artifact=parse,
    )
    projected = artifact.to_elaboration_result()
    assert projected.status is ElaborationStatus.OK
    assert projected.typed_expression is not None


# ---------------------------------------------------------------------------
# Codec round-trip
# ---------------------------------------------------------------------------


def test_codec_round_trip_parse_artifact_v2() -> None:
    artifact = _ok_parse_artifact()
    codec = TypedLogicCodec()
    envelope = codec.encode(artifact)
    assert envelope.kind is CodecKind.PARSE_ARTIFACT_V2
    restored = codec.decode(envelope)
    assert isinstance(restored, ParseArtifactV2)
    assert restored.content_digest == artifact.content_digest
    assert restored.lineage_digest == artifact.lineage_digest
    assert restored.source_digest == artifact.source_digest


def test_codec_round_trip_elaboration_artifact_v2() -> None:
    document = _document("P")
    parse = _ok_parse_artifact(document)
    elaborator = LogicElaborator(signature=propositional_signature("sig:p", ("P",)))
    artifact = elaborator.elaborate_artifact(
        mk_predicate("n:p", "P"),
        parse_artifact=parse,
        artifact_id="art:elab:codec",
    )
    codec = TypedLogicCodec()
    restored = codec.decode(codec.encode(artifact))
    assert isinstance(restored, ElaborationArtifactV2)
    assert restored.content_digest == artifact.content_digest
    assert restored.lineage_digest == artifact.lineage_digest
    assert restored.backend_ready is True


def test_module_round_trip_helper_for_parse_artifact() -> None:
    artifact = _ok_parse_artifact()
    restored = round_trip(artifact)
    assert isinstance(restored, ParseArtifactV2)
    assert restored.artifact_id == artifact.artifact_id
