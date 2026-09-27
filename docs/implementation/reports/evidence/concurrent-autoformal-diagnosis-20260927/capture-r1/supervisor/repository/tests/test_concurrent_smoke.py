"""A real concurrent smoke, followed by immutable receipt revalidation."""
import hashlib
import importlib.util
import json
from pathlib import Path


def test_real_concurrent_autoformal_smoke():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'smoke-config.json').read_bytes())
    for relative, expected in config['bundle_sha256'].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
    path = root / 'harness' / 'parent_harness.py'
    spec = importlib.util.spec_from_file_location('concurrent_smoke_parent', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = Path(config['lane_directory'])
    report = module.check_existing(output) if output.exists() else module.run_smoke(output)
    assert report['passed'] is True
    assert report['admitted'] is False
    assert report['formalized'] is False
    assert report['production_promotion'] is False
    raw = (output / 'smoke-receipt.json').read_bytes()
    assert json.loads(raw) == report
    target = root / 'results' / 'smoke.json'
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    module.check_existing(output)
