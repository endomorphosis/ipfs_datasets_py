"""Conformance: software_contracts AST IR syntax-kernel bridge (LFP-039).

Acceptance:

* Round trips preserve domain invariants and source identities
* No bridge weakens existing typed models to arbitrary JSON/text
* Loss and unsupported semantics are explicit

Interfaces: SoftwareContractsSyntaxBridge@1
"""

from __future__ import annotations

import pytest

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
    UnsupportedConstruct,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.syntax_bridge import (
    SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE,
    BridgeLossRecord,
    FreeFormRejectedError,
    LossKind,
    SoftwareContractsBridgeError,
    SoftwareContractsSyntaxBridge,
    UnsupportedConstructRecord,
    domain_identity_of,
    publish_software_contracts_ast,
    round_trip_software_contracts_ast,
    source_identities_of,
)
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind, TypedExpression, mk_true
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


SOURCE = b"import os\n\nasync def fetch(value: int = 0) -> str:\n    return await client(value=value)\n"


def span(
    start_byte: int,
    end_byte: int,
    start_line: int = 1,
    end_line: int | None = None,
    start_column: int = 0,
    end_column: int = 0,
) -> SourceSpan:
    return SourceSpan(
        start_byte=start_byte,
        end_byte=end_byte,
        start_line=start_line,
        start_column=start_column,
        end_line=end_line if end_line is not None else start_line,
        end_column=end_column if end_column else max(end_byte - start_byte, 0),
    )


def frontend() -> FrontendCapability:
    return FrontendCapability(
        frontend_name="cpython-ast",
        frontend_version="3.12.4",
        language="python",
        language_version="3.12",
        capabilities=(
            "unsupported_constructs",
            "symbols",
            "references",
            "modules",
            "calls",
        ),
        source_extensions=(".pyi", ".py"),
        toolchain_cid=cid_for_structured(
            {"frontend": "cpython-ast", "version": "3.12.4"}
        ),
    )


def complete_record(*, with_unsupported: bool = True) -> ASTRecord:
    whole = span(0, len(SOURCE), 1, 4)
    function_span = span(23, len(SOURCE), 2, 4)
    call_span = span(76, 95, 3)
    root_scope = ScopeDefinition(
        scope_id="scope:module",
        kind="module",
        span=whole,
    )
    function_scope = ScopeDefinition(
        scope_id="scope:function:fetch",
        kind="function",
        span=function_span,
        parent_scope_id="scope:module",
        owner_symbol_id="symbol:fetch:0",
    )
    signature = SignatureDefinition(
        parameters=(
            ParameterDefinition(
                name="value",
                kind="positional_or_named",
                position=0,
                annotation="int",
                default_kind="literal",
            ),
        ),
        return_annotation="str",
        is_async=True,
    )
    symbol = SymbolDefinition(
        symbol_id="symbol:fetch:0",
        name="fetch",
        qualified_name="example.fetch",
        kind="function",
        scope_id="scope:module",
        span=function_span,
        definition_ordinal=0,
        signature=signature,
        visibility="public",
        decorator_names=(),
        flags=("coroutine",),
    )
    reference = ReferenceRecord(
        reference_id="reference:client:0",
        name="client",
        scope_id="scope:function:fetch",
        context="call",
        span=call_span,
    )
    unsupported: tuple[UnsupportedConstruct, ...] = ()
    if with_unsupported:
        unsupported = (
            UnsupportedConstruct(
                unsupported_id="unsupported:dynamic-import:0",
                code="frontend.dynamic_import",
                construct="dynamic_import",
                reason="Dynamic import targets are not statically enumerable.",
                span=span(0, 1),
            ),
        )
    return ASTRecord(
        provenance=SourceProvenance(
            source_cid=cid_for_bytes(SOURCE),
            path="src/example.py",
            repository_id="repository:example",
            revision="0123456789abcdef",
            repository_tree_cid=cid_for_structured({"git_tree": "abc123"}),
        ),
        frontend=frontend(),
        module=ModuleDefinition(
            module_id="module:example",
            name="example",
            scope_id="scope:module",
            span=whole,
            export_names=("fetch",),
        ),
        scopes=(function_scope, root_scope),
        symbols=(symbol,),
        imports=(
            ImportDefinition(
                import_id="import:os.environ:0",
                scope_id="scope:module",
                module="os",
                kind="symbol",
                span=span(0, 22),
                imported_name="environ",
                local_name="environ",
            ),
        ),
        references=(reference,),
        calls=(
            CallRecord(
                call_id="call:client:0",
                scope_id="scope:function:fetch",
                callee_name="client",
                kind="direct",
                argument_count=1,
                span=call_span,
                callee_reference_id=reference.reference_id,
                named_argument_names=("value",),
                is_awaited=True,
            ),
        ),
        effects=(
            EffectRecord(
                effect_id="effect:raise:0",
                scope_id="scope:function:fetch",
                kind="exception",
                operation="raise",
                span=span(100, 120, 4),
                subject="RuntimeError",
            ),
            EffectRecord(
                effect_id="effect:await:0",
                scope_id="scope:function:fetch",
                kind="await",
                operation="await",
                span=call_span,
                subject="client",
            ),
        ),
        diagnostics=(
            DiagnosticRecord(
                code="frontend.unbound_candidate",
                severity="warning",
                message="client requires a separate resolution pass",
                span=call_span,
            ),
        ),
        unsupported=unsupported,
    )


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    assert (
        SoftwareContractsSyntaxBridge.INTERFACE
        == SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE
    )
    assert bridge.interface == "SoftwareContractsSyntaxBridge@1"
    assert bridge.domain_id == "software_contracts"
    wire = bridge.to_dict()
    assert wire["interface"] == SOFTWARE_CONTRACTS_SYNTAX_BRIDGE_INTERFACE
    assert wire["weakens_to_free_form"] is False
    assert wire["route"]["kind"] == "ast_ir"
    assert wire["route"]["family_id"] == "program"


# ---------------------------------------------------------------------------
# Round trips preserve domain and source identities
# ---------------------------------------------------------------------------


def test_round_trip_preserves_ast_cid_and_source_identities() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    record = complete_record()
    result = bridge.round_trip(record)
    assert result.ok
    assert result.exact
    assert result.domain_identity == record.cid
    assert result.domain_identity == domain_identity_of(record)
    assert result.document is not None
    assert result.document.cid == record.cid
    assert result.document.to_dict() == record.to_dict()
    assert (
        result.document.provenance.source_cid == record.provenance.source_cid
    )
    sources = set(source_identities_of(record))
    assert sources <= set(result.source_identities)
    assert record.provenance.source_cid in result.source_identities
    assert record.provenance.repository_id in result.source_identities
    assert record.module.module_id in result.source_identities


def test_publish_and_helper_round_trip() -> None:
    record = complete_record()
    published = publish_software_contracts_ast(record)
    assert published.exact
    assert published.expression is not None
    assert published.expression.root.kind is NodeKind.EXTENSION
    restored = round_trip_software_contracts_ast(record)
    assert restored.domain_identity == record.cid


def test_mapping_input_is_reconstructed_as_typed_ast() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    record = complete_record()
    result = bridge.publish(record.to_dict())
    assert result.exact
    assert result.domain_identity == record.cid


# ---------------------------------------------------------------------------
# Explicit unsupported constructs survive
# ---------------------------------------------------------------------------


def test_unsupported_constructs_remain_explicit() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    record = complete_record(with_unsupported=True)
    result = bridge.round_trip(record)
    assert result.unsupported
    ids = {item.construct_id for item in result.unsupported}
    assert "unsupported:dynamic-import:0" in ids
    assert result.document is not None
    assert len(result.document.unsupported) == 1
    assert result.document.unsupported[0].construct == "dynamic_import"


def test_unsupported_absence_is_also_preserved() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    record = complete_record(with_unsupported=False)
    result = bridge.round_trip(record)
    assert result.unsupported == ()
    assert result.document is not None
    assert result.document.unsupported == ()


# ---------------------------------------------------------------------------
# No free-form weakening
# ---------------------------------------------------------------------------


def test_free_form_text_is_rejected() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    with pytest.raises(FreeFormRejectedError) as excinfo:
        bridge.publish("def f(): pass")
    assert excinfo.value.code == "software_contracts.free_form_rejected"


def test_published_payload_is_typed_extension_not_text() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    result = bridge.publish(complete_record())
    extension = result.expression.root.extension
    assert extension is not None
    payload = dict(extension.payload)
    assert payload["kind"] == "ast_ir"
    assert isinstance(payload["document"], dict)
    assert payload["document"]["schema"]
    assert "text" not in payload
    assert "raw" not in payload
    assert payload["domain_identity"] == result.domain_identity


def test_consume_rejects_non_extension_roots() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    signature = propositional_signature("sig:prop", ("p",))
    expression = TypedExpression(
        expression_id="expr:true",
        root=mk_true("node:true"),
        signature=signature,
        elaborate_on_init=False,
    )
    with pytest.raises(FreeFormRejectedError):
        bridge.consume(expression)


def test_malformed_mapping_fails_closed() -> None:
    bridge = SoftwareContractsSyntaxBridge()
    with pytest.raises(SoftwareContractsBridgeError):
        bridge.publish({"schema": "not-an-ast", "text": "x"})


# ---------------------------------------------------------------------------
# Explicit loss surface
# ---------------------------------------------------------------------------


def test_loss_records_are_explicit_and_serializable() -> None:
    loss = BridgeLossRecord(
        loss_id="loss:demo",
        kind=LossKind.SOURCE_MAP,
        path="source_identities",
        description="declared source identity missing after reconstruction",
    )
    unsupported = UnsupportedConstructRecord(
        construct_id="unsupported:demo",
        construct="eval_call",
        reason="eval is not admitted by the frontend capability set",
        path="frontend.unsupported",
    )
    assert loss.to_dict()["kind"] == "source_map"
    assert unsupported.to_dict()["construct"] == "eval_call"


def test_bridge_error_codes_are_stable() -> None:
    err = SoftwareContractsBridgeError(
        "boom", code="software_contracts.route_error"
    )
    assert err.to_dict()["code"] == "software_contracts.route_error"
