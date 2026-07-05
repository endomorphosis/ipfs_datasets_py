from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import TypeScriptSchemaEmitter
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model


def test_typescript_schema_emitter_outputs_runtime_guard_and_metadata() -> None:
    """GIVEN a security model WHEN emitting TypeScript schema THEN a real schema module is produced."""

    rendered = TypeScriptSchemaEmitter().emit_schema(example_minimal_exchange_model())
    assert 'export interface SecurityModelIR {' in rendered
    assert 'export function isSecurityModelIR' in rendered
    assert 'SECURITY_MODEL_IR_SCHEMA_VERSION' in rendered
    assert '"proverTargets": [' in rendered
