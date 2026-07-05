import shutil
import subprocess

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import TypeScriptSchemaEmitter
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model



def test_typescript_schema_compiles_when_tsc_is_available(tmp_path) -> None:
    node = shutil.which('node')
    tsc = shutil.which('tsc') or shutil.which('npx')
    if not node or not tsc:
        pytest.skip('node and tsc/npx are not available')
    schema_path = tmp_path / 'security_schema.ts'
    schema_path.write_text(TypeScriptSchemaEmitter().emit_schema(example_minimal_exchange_model()), encoding='utf-8')
    (tmp_path / 'tsconfig.json').write_text(
        '{"compilerOptions":{"strict":true,"target":"ES2020","module":"CommonJS","noEmit":true},"files":["security_schema.ts"]}',
        encoding='utf-8',
    )
    if tsc.endswith('npx'):
        command = [tsc, 'tsc', '--noEmit', '--project', str(tmp_path / 'tsconfig.json')]
    else:
        command = [tsc, '--noEmit', '--project', str(tmp_path / 'tsconfig.json')]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)
