"""Deterministic, content-addressed software-contract analysis primitives.

Shared AST/schema exports are serialized under DSCON-G105.  Language
frontends import this surface and keep their syntax-specific records in their
own modules.
"""

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTIRValidationError,
    ASTRecord,
    CallRecord,
    CallSite,
    CanonicalASTRecord,
    Diagnostic,
    DiagnosticRecord,
    Effect,
    EffectRecord,
    FrontendCapability,
    ImportDefinition,
    ModuleDefinition,
    ParameterDefinition,
    ReferenceRecord,
    ScopeDefinition,
    Signature,
    SignatureDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
    SymbolReference,
    UnsupportedConstruct,
    ast_ir_schema_descriptor,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_SCHEMA,
    AST_IR_SCHEMA_VERSION,
    FRONTEND_CAPABILITY_SCHEMA,
    FRONTEND_CAPABILITY_SCHEMA_VERSION,
    SCHEMA_VERSIONS,
    SchemaVersion,
    SchemaVersionError,
    get_schema_version,
    schema_registry_descriptor,
)


__all__ = [
    "ASTIRValidationError",
    "ASTRecord",
    "AST_IR_SCHEMA",
    "AST_IR_SCHEMA_VERSION",
    "CallRecord",
    "CallSite",
    "CanonicalASTRecord",
    "Diagnostic",
    "DiagnosticRecord",
    "Effect",
    "EffectRecord",
    "FRONTEND_CAPABILITY_SCHEMA",
    "FRONTEND_CAPABILITY_SCHEMA_VERSION",
    "FrontendCapability",
    "ImportDefinition",
    "ModuleDefinition",
    "ParameterDefinition",
    "ReferenceRecord",
    "SCHEMA_VERSIONS",
    "SchemaVersion",
    "SchemaVersionError",
    "ScopeDefinition",
    "Signature",
    "SignatureDefinition",
    "SourceProvenance",
    "SourceSpan",
    "SymbolDefinition",
    "SymbolReference",
    "UnsupportedConstruct",
    "ast_ir_schema_descriptor",
    "get_schema_version",
    "schema_registry_descriptor",
]
