"""Shared normalized AST/symbol IR tests (DSCON-G105/G110/G120 packet)."""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType
from typing import Any

import pytest

import ipfs_datasets_py.logic.software_contracts as package
from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTIRValidationError,
    ASTRecord,
    CallRecord,
    DiagnosticRecord,
    EffectRecord,
    FrontendCapability,
    ImportDefinition,
    MAX_SAFE_INTEGER,
    ModuleDefinition,
    ParameterDefinition,
    ReferenceRecord,
    ScopeDefinition,
    SignatureDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
    UnsupportedConstruct,
    ast_ir_schema_descriptor,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_OBJECTIVE_VALIDATION_SCHEMA,
    AST_IR_OWNER_GOAL_ID,
    AST_IR_PACKET_GOAL_IDS,
    AST_IR_REPAIR_TASK_ID,
    AST_IR_SCHEMA_VERSION,
    AST_IR_VALIDATED_ARTIFACTS,
    AST_IR_VALIDATION_COMMAND,
    FRONTEND_CAPABILITY_SCHEMA_VERSION,
    OBJECTIVE_VALIDATION_EVIDENCE,
    SCHEMA_VERSIONS,
    SchemaVersion,
    SchemaVersionError,
    ast_ir_objective_validation_contract,
    get_schema_version,
    schema_registry_descriptor,
)


SOURCE = (
    b"from os import environ\n"
    b"async def fetch(value: int = 1) -> str:\n"
    b"    await client(value=value)\n"
    b"    raise RuntimeError()\n"
)


def span(
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


def frontend(
    *,
    capabilities: tuple[str, ...] = (
        "unsupported_constructs",
        "symbols",
        "references",
        "modules",
        "calls",
    ),
) -> FrontendCapability:
    return FrontendCapability(
        frontend_name="cpython-ast",
        frontend_version="3.12.4",
        language="python",
        language_version="3.12",
        capabilities=capabilities,
        source_extensions=(".pyi", ".py"),
        toolchain_cid=cid_for_structured(
            {"frontend": "cpython-ast", "version": "3.12.4"}
        ),
    )


def complete_record() -> ASTRecord:
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
        # Input order is intentionally reversed; AST canonicalizes source facts.
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
        unsupported=(
            UnsupportedConstruct(
                unsupported_id="unsupported:dynamic-import:0",
                code="frontend.dynamic_import",
                construct="dynamic_import",
                reason="Dynamic import targets are not statically enumerable.",
                span=span(0, 1),
            ),
        ),
    )


def test_schema_registry_is_exact_immutable_and_deterministic() -> None:
    assert isinstance(SCHEMA_VERSIONS, MappingProxyType)
    assert get_schema_version(AST_IR_SCHEMA_VERSION.identifier) is AST_IR_SCHEMA_VERSION
    assert (
        get_schema_version(FRONTEND_CAPABILITY_SCHEMA_VERSION.identifier)
        is FRONTEND_CAPABILITY_SCHEMA_VERSION
    )
    with pytest.raises(TypeError):
        SCHEMA_VERSIONS["new@1"] = AST_IR_SCHEMA_VERSION  # type: ignore[index]
    with pytest.raises(SchemaVersionError):
        get_schema_version(" ipfs-datasets.software-contracts.ast-ir@1.0.0")

    descriptor = schema_registry_descriptor()
    assert descriptor["owner_goal"] == "DSCON-G105"
    assert descriptor["compatibility"] == "exact-version-only"
    assert [item["identifier"] for item in descriptor["schemas"]] == sorted(
        SCHEMA_VERSIONS
    )
    assert (
        cid_for_structured(descriptor)
        == "baguqeeraanunv3jqvjqsj757l6sxfmvyngl7bi4hr5fjpyrg432l7jdzek2q"
    )


def test_schema_version_rejects_ambiguous_components_and_closed_read_shape() -> None:
    with pytest.raises(SchemaVersionError):
        SchemaVersion("UPPER.invalid", 1)
    with pytest.raises(SchemaVersionError):
        SchemaVersion("valid.name", True)  # type: ignore[arg-type]
    with pytest.raises(SchemaVersionError):
        SchemaVersion("valid.name", 0)
    with pytest.raises(SchemaVersionError):
        SchemaVersion.from_dict(
            {
                **AST_IR_SCHEMA_VERSION.to_dict(),
                "identifier": "wrong@1.0.0",
            }
        )
    with pytest.raises(SchemaVersionError):
        SchemaVersion.from_dict(
            {**AST_IR_SCHEMA_VERSION.to_dict(), "future": "field"}
        )


def test_full_ast_round_trips_through_canonical_cid_profile_with_golden_root() -> None:
    record = complete_record()
    restored_from_mapping = ASTRecord.from_dict(record.to_dict())
    restored_from_json = ASTRecord.from_json(record.to_json())

    assert restored_from_mapping == restored_from_json == record
    assert record.to_json() == record.canonical_bytes.decode("utf-8")
    assert json.loads(record.to_json()) == record.to_dict()
    assert cid_for_structured(record.to_dict()) == record.cid
    assert record.verify_cid(record.cid) == record.cid
    # Golden root: schema/frontends cannot drift without an explicit review.
    assert (
        record.cid
        == "baguqeeraw7urbhc7vpj4us2wqekdisc6g4na2hjjvwq2quirp52p7hjtb4rq"
    )


def test_record_order_and_set_like_fields_are_canonicalized() -> None:
    first = complete_record()
    second = ASTRecord(
        provenance=first.provenance,
        frontend=frontend(capabilities=tuple(reversed(first.frontend.capabilities))),
        module=first.module,
        scopes=tuple(reversed(first.scopes)),
        symbols=first.symbols,
        imports=first.imports,
        references=first.references,
        calls=first.calls,
        effects=tuple(reversed(first.effects)),
        diagnostics=first.diagnostics,
        unsupported=first.unsupported,
    )
    assert second == first
    assert second.cid == first.cid
    assert [item.scope_id for item in first.scopes] == [
        "scope:module",
        "scope:function:fetch",
    ]
    assert [item.effect_id for item in first.effects] == [
        "effect:await:0",
        "effect:raise:0",
    ]
    assert first.frontend.source_extensions == (".py", ".pyi")


def test_records_are_frozen_and_defensively_detach_ordered_inputs() -> None:
    mutable_capabilities = ["symbols", "modules"]
    capability = frontend(capabilities=mutable_capabilities)  # type: ignore[arg-type]
    mutable_capabilities.append("calls")
    assert capability.capabilities == ("modules", "symbols")
    with pytest.raises(dataclasses.FrozenInstanceError):
        capability.language = "typescript"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        complete_record().module.name = "changed"  # type: ignore[misc]


def test_parsing_facts_do_not_claim_resolution() -> None:
    payload = complete_record().to_dict()
    reference = payload["references"][0]
    call = payload["calls"][0]
    forbidden = {
        "resolved_symbol_id",
        "target_symbol_id",
        "candidate_symbol_ids",
        "resolution_confidence",
    }
    assert forbidden.isdisjoint(reference)
    assert forbidden.isdisjoint(call)

    reference["target_symbol_id"] = "symbol:fetch:0"
    with pytest.raises(ASTIRValidationError, match="fields are closed"):
        ReferenceRecord.from_dict(reference)


def test_shared_schema_has_no_language_specific_escape_hatch() -> None:
    descriptor = ast_ir_schema_descriptor()
    assert (
        cid_for_structured(descriptor)
        == "baguqeerarrt5ravhwjwr75appwlkgf2qxrwp5v7wrm2mya6lqrqq37k6nzkq"
    )
    assert descriptor["guarantees"]["language_specific_payloads"] is False
    assert descriptor["guarantees"]["exact_shared_record_types"] is True
    assert descriptor["guarantees"]["parser_resolution_separated"] is True
    assert descriptor["guarantees"]["resolved_targets_in_ast"] is False
    assert descriptor["span_convention"] == {
        "byte_interval": "half-open",
        "byte_encoding": "utf-8",
        "line_base": 1,
        "column_base": 0,
    }
    for record_type in (
        ASTRecord,
        SymbolDefinition,
        ReferenceRecord,
        CallRecord,
        EffectRecord,
    ):
        fields = {item.name for item in dataclasses.fields(record_type)}
        assert fields.isdisjoint(
            {
                "metadata",
                "payload",
                "syntax",
                "python_ast",
                "typescript_ast",
                "resolved_targets",
            }
        )


def test_shared_schema_rejects_subclass_serialization_escape_hatches() -> None:
    """Frontend-owned syntax cannot enter the shared schema through subclasses."""

    class PythonSpecificASTRecord(ASTRecord):
        def to_dict(self) -> dict[str, Any]:
            return {**super().to_dict(), "python_ast": {"kind": "Module"}}

    record = complete_record()
    with pytest.raises(ASTIRValidationError, match="exact ASTRecord"):
        PythonSpecificASTRecord(
            **{
                field.name: getattr(record, field.name)
                for field in dataclasses.fields(ASTRecord)
            }
        )

    class PythonSpecificSpan(SourceSpan):
        def to_dict(self) -> dict[str, Any]:
            return {**super().to_dict(), "python_ast": "Name"}

    with pytest.raises(ASTIRValidationError, match="exact SourceSpan"):
        ModuleDefinition(
            module_id="module:x",
            name="x",
            scope_id="scope:x",
            span=PythonSpecificSpan(0, 1, 1, 0, 1, 1),
        )

    class PythonSpecificSymbol(SymbolDefinition):
        def to_dict(self) -> dict[str, Any]:
            return {**super().to_dict(), "python_ast": "FunctionDef"}

    frontend_symbol = PythonSpecificSymbol(
        **{
            field.name: getattr(record.symbols[0], field.name)
            for field in dataclasses.fields(SymbolDefinition)
        }
    )
    with pytest.raises(ASTIRValidationError, match="exact SymbolDefinition"):
        dataclasses.replace(record, symbols=(frontend_symbol,))

    class ExtendedSchemaVersion(SchemaVersion):
        pass

    extended_schema = ExtendedSchemaVersion(
        AST_IR_SCHEMA_VERSION.name,
        AST_IR_SCHEMA_VERSION.major,
        AST_IR_SCHEMA_VERSION.minor,
        AST_IR_SCHEMA_VERSION.patch,
    )
    with pytest.raises(ASTIRValidationError, match="ast_schema is invalid"):
        dataclasses.replace(record.frontend, ast_schema=extended_schema)


@pytest.mark.parametrize(
    ("language", "language_version", "extensions"),
    [
        ("python", "3.12", (".py", ".pyi")),
        (
            "typescript",
            "5.5",
            (".cjs", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"),
        ),
    ],
)
def test_python_and_typescript_frontends_share_the_same_ast_contract(
    language: str,
    language_version: str,
    extensions: tuple[str, ...],
) -> None:
    capability = FrontendCapability(
        frontend_name=f"{language}-frontend",
        frontend_version="1.0.0",
        language=language,
        language_version=language_version,
        capabilities=("calls", "modules", "references", "symbols"),
        source_extensions=tuple(reversed(extensions)),
        toolchain_cid=cid_for_structured(
            {"language": language, "version": language_version}
        ),
    )
    base = complete_record()
    record = dataclasses.replace(base, frontend=capability)
    assert ASTRecord.from_json(record.to_json()) == record
    assert record.schema_version == AST_IR_SCHEMA_VERSION
    assert record.frontend.source_extensions == extensions
    assert "syntax" not in record.to_dict()


def test_source_provenance_accepts_git_paths_with_internal_spaces() -> None:
    provenance = SourceProvenance(
        cid_for_bytes(b"x"),
        "src/generated module copy.py",
        "repository:x",
        "rev",
    )
    assert provenance.path == "src/generated module copy.py"
    assert SourceProvenance.from_dict(provenance.to_dict()) == provenance


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: SourceSpan(True, 1, 1, 0, 1, 1),  # type: ignore[arg-type]
            "start_byte",
        ),
        (
            lambda: SourceSpan(0, MAX_SAFE_INTEGER + 1, 1, 0, 1, 1),
            "end_byte",
        ),
        (lambda: SourceSpan(2, 1, 1, 0, 1, 1), "precedes"),
        (lambda: SourceSpan(0, 1, 2, 0, 1, 1), "precedes"),
        (
            lambda: SourceProvenance(
                cid_for_bytes(b"x"), "/absolute.py", "repository:x", "rev"
            ),
            "relative POSIX",
        ),
        (
            lambda: SourceProvenance(
                cid_for_bytes(b"x"), "../escape.py", "repository:x", "rev"
            ),
            "relative POSIX",
        ),
        (
            lambda: FrontendCapability(
                "frontend",
                "1",
                "python",
                "3.12",
                {"symbols"},  # type: ignore[arg-type]
                (".py",),
                cid_for_structured({"tool": "x"}),
            ),
            "ordered sequence",
        ),
    ],
)
def test_ambiguous_constructor_values_fail_closed(
    factory: Any, match: str
) -> None:
    with pytest.raises(ASTIRValidationError, match=match):
        factory()


def test_json_reader_rejects_duplicate_keys_floats_and_noncanonical_shapes() -> None:
    record = complete_record()
    with pytest.raises(ASTIRValidationError, match="duplicate JSON key"):
        ASTRecord.from_json('{"schema":"a","schema":"b"}')

    payload = record.to_json().replace('"argument_count":1', '"argument_count":1.0')
    with pytest.raises(ASTIRValidationError, match="rejects float"):
        ASTRecord.from_json(payload)

    payload_dict = record.to_dict()
    payload_dict["future_field"] = None
    with pytest.raises(ASTIRValidationError, match="fields are closed"):
        ASTRecord.from_dict(payload_dict)

    # Tuple is deterministic in Python but outside the reviewed DAG-JSON input
    # vocabulary; wire reads accept exact JSON arrays only.
    payload_dict = record.to_dict()
    payload_dict["calls"] = tuple(payload_dict["calls"])
    with pytest.raises(ASTIRValidationError, match="strict canonical mapping"):
        ASTRecord.from_dict(payload_dict)


def test_cid_verification_detects_tampering() -> None:
    record = complete_record()
    tampered = ASTRecord(
        provenance=record.provenance,
        frontend=record.frontend,
        module=ModuleDefinition(
            module_id=record.module.module_id,
            name="renamed",
            scope_id=record.module.scope_id,
            span=record.module.span,
            export_names=record.module.export_names,
        ),
        scopes=record.scopes,
        symbols=record.symbols,
        imports=record.imports,
        references=record.references,
        calls=record.calls,
        effects=record.effects,
        diagnostics=record.diagnostics,
        unsupported=record.unsupported,
    )
    with pytest.raises(ValueError, match="does not match"):
        tampered.verify_cid(record.cid)


def test_graph_rejects_dangling_duplicate_and_cyclic_records() -> None:
    record = complete_record()
    with pytest.raises(ASTIRValidationError, match="duplicate scope_id"):
        dataclasses.replace(record, scopes=record.scopes + (record.scopes[0],))

    dangling_call = dataclasses.replace(
        record.calls[0], callee_reference_id="reference:missing"
    )
    with pytest.raises(ASTIRValidationError, match="unknown callee_reference_id"):
        dataclasses.replace(record, calls=(dangling_call,))

    dangling_symbol = dataclasses.replace(
        record.symbols[0], scope_id="scope:missing"
    )
    with pytest.raises(ASTIRValidationError, match="unknown scope_id"):
        dataclasses.replace(record, symbols=(dangling_symbol,))

    cyclic_root = dataclasses.replace(
        record.scopes[0], parent_scope_id=record.scopes[1].scope_id
    )
    with pytest.raises(ASTIRValidationError):
        dataclasses.replace(record, scopes=(cyclic_root, record.scopes[1]))


def test_duplicate_definitions_remain_explicit_by_ordinal() -> None:
    record = complete_record()
    duplicate = dataclasses.replace(
        record.symbols[0],
        symbol_id="symbol:fetch:1",
        definition_ordinal=1,
        span=span(121, 140, 5),
    )
    updated = dataclasses.replace(
        record,
        symbols=record.symbols + (duplicate,),
    )
    assert [item.definition_ordinal for item in updated.symbols] == [0, 1]
    assert [item.name for item in updated.symbols] == ["fetch", "fetch"]


def test_frontend_identity_binds_toolchain_capabilities_and_schema() -> None:
    capability = frontend()
    payload = capability.to_dict()
    assert payload["schema"] == FRONTEND_CAPABILITY_SCHEMA_VERSION.identifier
    assert payload["ast_schema"] == AST_IR_SCHEMA_VERSION.to_dict()
    assert payload["toolchain_cid"].startswith("bagu")
    assert FrontendCapability.from_dict(payload) == capability

    changed = frontend(capabilities=capability.capabilities + ("effects",))
    assert changed.cid != capability.cid
    with pytest.raises(ASTIRValidationError, match="toolchain_cid"):
        dataclasses.replace(capability, toolchain_cid="sha256:not-a-cid")


def test_signature_preserves_semantic_shape_without_default_expressions() -> None:
    signature = complete_record().symbols[0].signature
    assert signature is not None
    parameter = signature.parameters[0]
    assert parameter.has_default
    assert parameter.default_kind == "literal"
    assert "default_value" not in parameter.to_dict()
    assert signature.is_async
    assert not signature.is_generator

    with pytest.raises(ASTIRValidationError, match="contiguous"):
        SignatureDefinition(
            parameters=(
                ParameterDefinition("x", "positional_or_named", 1),
            )
        )


def test_unsupported_constructs_and_diagnostics_are_durable_facts() -> None:
    record = complete_record()
    assert record.unsupported[0].code == "frontend.dynamic_import"
    assert record.diagnostics[0].severity == "warning"
    restored = ASTRecord.from_json(record.to_json())
    assert restored.unsupported == record.unsupported
    assert restored.diagnostics == record.diagnostics

    unlocated = dataclasses.replace(
        record,
        diagnostics=(
            DiagnosticRecord(
                code="frontend.parse_error",
                severity="fatal",
                message="Parser failed before a source location was available.",
            ),
        ),
    )
    assert unlocated.diagnostics[0].span is None


def test_package_exports_are_the_serialized_shared_surface() -> None:
    required = {
        "ASTRecord",
        "SymbolDefinition",
        "SourceSpan",
        "FrontendCapability",
        "SchemaVersion",
        "ReferenceRecord",
        "CallRecord",
        "EffectRecord",
        "UnsupportedConstruct",
        "ast_ir_objective_validation_contract",
    }
    assert required.issubset(package.__all__)
    assert package.ASTRecord is ASTRecord
    assert package.SymbolDefinition is SymbolDefinition
    assert package.SchemaVersion is SchemaVersion
    assert package.Signature is SignatureDefinition
    assert package.SymbolReference is ReferenceRecord
    assert package.CallSite is CallRecord
    assert package.Effect is EffectRecord
    assert package.Diagnostic is DiagnosticRecord
    assert (
        package.ast_ir_objective_validation_contract
        is ast_ir_objective_validation_contract
    )


def test_objective_validation_repair_contract_covers_the_goal_packet() -> None:
    """Objective validation repair for DSCON-074 / G105, G110, and G120."""

    assert OBJECTIVE_VALIDATION_EVIDENCE == "objective validation repair"
    assert AST_IR_OWNER_GOAL_ID == "DSCON-G105"
    assert AST_IR_REPAIR_TASK_ID == "DSCON-074"
    assert AST_IR_PACKET_GOAL_IDS == (
        "DSCON-G105",
        "DSCON-G110",
        "DSCON-G120",
    )
    assert AST_IR_VALIDATION_COMMAND == (
        "python -m pytest -q "
        "ipfs_datasets_py/tests/unit/logic/software_contracts/test_ast_ir.py"
    )
    assert AST_IR_VALIDATED_ARTIFACTS == (
        "ipfs_datasets_py/ipfs_datasets_py/logic/software_contracts/__init__.py",
        "ipfs_datasets_py/ipfs_datasets_py/logic/software_contracts/ast_ir.py",
        "ipfs_datasets_py/ipfs_datasets_py/logic/software_contracts/schema_versions.py",
        "ipfs_datasets_py/tests/unit/logic/software_contracts/test_ast_ir.py",
    )

    contract = ast_ir_objective_validation_contract()
    assert contract["schema"] == AST_IR_OBJECTIVE_VALIDATION_SCHEMA
    assert contract["evidence_term"] == OBJECTIVE_VALIDATION_EVIDENCE
    assert contract["owner_goal"] == AST_IR_OWNER_GOAL_ID
    assert contract["repair_task_id"] == AST_IR_REPAIR_TASK_ID
    assert contract["packet_goals"] == list(AST_IR_PACKET_GOAL_IDS)
    assert contract["validation_command"] == AST_IR_VALIDATION_COMMAND
    assert contract["validated_artifacts"] == list(AST_IR_VALIDATED_ARTIFACTS)
    assert all(contract["acceptance"].values())
    assert (
        cid_for_structured(contract)
        == "baguqeerah4svrevky46uybjnyupgdw65z2ttssdeet4pys32pk5jxff33zdq"
    )
