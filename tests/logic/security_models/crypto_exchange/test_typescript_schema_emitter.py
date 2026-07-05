from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import TypeScriptSchemaEmitter
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model



def test_typescript_schema_emitter_outputs_runtime_guard_and_metadata() -> None:
    rendered = TypeScriptSchemaEmitter().emit_schema(example_minimal_exchange_model())
    assert 'export interface SecurityModelIR {' in rendered
    assert 'export interface ProofReport {' in rendered
    assert 'export interface ProofReceipt {' in rendered
    assert 'export function validateSecurityModelIR' in rendered
    assert 'export function validateProofReport' in rendered
    assert 'export function validateProofReceipt' in rendered
    assert 'canonicalizeJson' in rendered
