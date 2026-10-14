"""Unexecuted authored300-source semantic completion fixture and protocol data.

Targets are source bytes only. Neither qualification tests nor analyzers import
the pytest modules or execute their tests/fixtures. Global graph assertions
cover relationships crossing the admitted prefix and near the final preparation page.
"""
from pathlib import Path
from contextlib import contextmanager
import base64
import hashlib
import json
import math

REPOSITORY_ID = 'preparation-full300:authored-300-source-fixture'
CREATED_AT = 1700000000.0
SUCCESSOR_CREATED_AT = CREATED_AT + 100.0
OPERATION_ID = 'full300-authored-initial-v1'
SUCCESSOR_OPERATION_ID = 'full300-authored-successor-v1'
PREFIX_ENTRIES = 128
ENTRY_COUNT = 300
PYTHON_COUNT = 299
MAX_ENTRIES = 320
SOURCES = {f'a{i:03d}.py':
           ('def step_%03d(value):\n    return value + %d\n' % (i, i + 1)).encode('ascii')
           for i in range(296)}
SOURCES['a000.py'] = b'from a128 import cross_page\ndef service(value):\n    return cross_page(value) + 1\n'
SOURCES['a127.py'] = b'def boundary(value):\n    return value + 15\n'
SOURCES['a128.py'] = b'from a127 import boundary\nfrom a295 import near_end\ndef cross_page(value):\n    return boundary(value) + near_end(value)\n'
SOURCES['a295.py'] = b'from a000 import service\ndef near_end(value):\n    return value + 295\ndef late(value):\n    return service(value) + near_end(value)\n'
SOURCES['conftest.py'] = (
    b'import pytest\nfrom a128 import cross_page\n'
    b'@pytest.fixture(scope="session")\ndef root_value():\n    return 7\n'
    b'@pytest.fixture\ndef computed(root_value):\n    return cross_page(root_value)\n')
SOURCES['pyproject.toml'] = (
    b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    b'markers = ["integration: authored static qualification fixture"]\naddopts = "-q"\n')
SOURCES['tests/test_cross_page.py'] = (
    b'from a000 import service\ndef test_cross_page(computed):\n    assert service(computed) > 0\n')
SOURCES['tests/test_late.py'] = (
    b'import pytest\nfrom a295 import late\n@pytest.mark.integration\n'
    b'def test_tail(computed):\n    assert late(computed) >= 1\n')
ORDERED_PATHS = tuple(sorted(SOURCES))
PYTHON_PATHS = tuple(path for path in ORDERED_PATHS if path.endswith('.py'))
PAGE_PARTITIONS = tuple(ORDERED_PATHS[start:start + 16] for start in range(0, ENTRY_COUNT, 16))
SUCCESSOR_SOURCES = {**SOURCES, 'a295.py': SOURCES['a295.py'].replace(b'return value + 295', b'return value + 1295')}
TABLE_NAMES = ('source_revisions', 'source_files', 'ast_blobs', 'ast_nodes', 'scopes',
               'symbols', 'imports', 'references', 'calls', 'effects', 'interfaces',
               'diagnostics', 'invalidations')
CALL_RELATIONSHIPS = (
    (('a000.py', 'service'), ('a128.py', 'cross_page')),
    (('a128.py', 'cross_page'), ('a127.py', 'boundary')),
    (('a128.py', 'cross_page'), ('a295.py', 'near_end')),
    (('tests/test_late.py', 'test_tail'), ('a295.py', 'late')),
)


def write_fixture(repository):
    if type(repository) is not type(Path.cwd()):
        raise ValueError('exact concrete owned fixture Path required')
    repository.mkdir(mode=0o700)
    for name, raw in sorted(SOURCES.items()):
        target = repository / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
    if len(SOURCES) != ENTRY_COUNT or len(PYTHON_PATHS) != PYTHON_COUNT:
        raise AssertionError('finite fixture inventory changed')
    return dict(SOURCES)


def graph_witnesses(state):
    """Return actual selected edges, refusing missing cross-page relationships."""
    symbols = {(row.module_path, row.qualified_name.rsplit('.', 1)[-1]): row
               for row in state.symbols if row.kind in {'function', 'async_function', 'test', 'fixture'}}
    edges = {(row.source_id, row.target_id, row.relation): row for row in state.edges}
    calls = []
    for source, target in CALL_RELATIONSHIPS:
        if source not in symbols or target not in symbols:
            raise AssertionError('missing authored cross-page symbol: ' + repr((source, target)))
        key = (symbols[source].stable_id, symbols[target].stable_id, 'calls')
        if key not in edges:
            raise AssertionError('missing resolved authored cross-page call: ' + repr((source, target)))
        calls.append(edges[key].to_dict())
    computed = symbols[('conftest.py', 'computed')]
    root = symbols[('conftest.py', 'root_value')]
    fixtures = []
    for key in (('tests/test_cross_page.py', 'test_cross_page'), ('tests/test_late.py', 'test_tail')):
        test = symbols[key]
        edge = edges.get((test.stable_id, computed.stable_id, 'uses_fixture'))
        if edge is None:
            raise AssertionError('missing cross-page visible pytest fixture: ' + repr(key))
        fixtures.append(edge.to_dict())
    dependency = edges.get((computed.stable_id, root.stable_id, 'uses_fixture'))
    if dependency is None:
        raise AssertionError('missing computed fixture dependency')
    fixtures.append(dependency.to_dict())
    configuration = [row for row in state.artifacts if row.path == 'pyproject.toml'
                     and row.kind == 'pytest_config']
    if len(configuration) != 1:
        raise AssertionError('missing exact authored pytest configuration')
    configured = [row.to_dict() for row in state.edges if row.relation == 'configured_by'
                  and row.target_id == configuration[0].artifact_id]
    if len(configured) < 2:
        raise AssertionError('configuration must apply to both last-page tests')
    return {'cross_page_calls': calls, 'pytest_fixture_dependencies': fixtures,
            'pytest_configuration': configuration[0].to_dict(), 'configured_tests': configured}


def apply_successor(repository):
    target = repository / 'a295.py'
    if target.read_bytes() != SOURCES['a295.py']:
        raise ValueError('successor requires the exact admitted initial late source')
    target.write_bytes(SUCCESSOR_SOURCES['a295.py'])
    return dict(SUCCESSOR_SOURCES)


@contextmanager
def fixed_module_clocks(created_at, *modules):
    """Fixture-only attribute delegates; shared stdlib/MAIN clock is untouched."""
    if type(created_at) not in (int, float) or not math.isfinite(created_at):
        raise ValueError('finite exact fixture clock required')
    saved = [(module, module.time) for module in modules]
    class Clock:
        def __init__(self, original): self.original = original
        def time(self): return float(created_at)
        def __getattr__(self, name): return getattr(self.original, name)
    try:
        for module, original in saved: module.time = Clock(original)
        yield
    finally:
        for module, original in reversed(saved): module.time = original


def cache_fingerprint(raw):
    digest = hashlib.sha256(raw).digest()
    return {'bytes': len(raw), 'sha256': digest.hex(),
            'raw_cid_v1': 'b' + base64.b32encode(b'\x01\x55\x12\x20' + digest).decode().lower().rstrip('=')}


def admit_prefix_cache(raw, anchor, ingestor, projections, *, optimized_handoff_cache=True):
    """Fixture profile only: hydrate independently admitted historical128 shards.

    The caller must first verify live sources, the external root/prior-page
    admission and these canonical prefix projections. This performs no SQL,
    active publication, source freshness assertion or proof admission. False
    skips decoding, cache retrieval and hydration independently of other flags.
    """
    if type(optimized_handoff_cache) is not bool:
        raise ValueError('optimized_handoff_cache must be an exact boolean')
    if not optimized_handoff_cache:
        return {'optimized_handoff_cache': False, 'restored_entries': 0}
    from ipfs_datasets_py.logic.software_contracts import duckdb_ingest as ingestion
    from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes
    if (type(raw) is not bytes or not 0 < len(raw) <= 16 * 1024**2
            or type(anchor) is not dict or set(anchor) != {'bytes', 'sha256', 'raw_cid_v1'}
            or cache_fingerprint(raw) != anchor):
        raise ValueError('independent historical cache RAW admission differs')
    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value: raise ValueError('duplicate cache key refused')
            value[name] = item
        return value
    def nonfinite(value): raise ValueError('nonfinite cache value refused')
    parsed = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    if (canonical_dag_json_bytes(parsed) != raw or type(parsed) is not dict
            or set(parsed) != {'schema', 'entries'}
            or parsed['schema'] != ingestion.SOURCE_SHARD_RESTART_SCHEMA
            or type(parsed['entries']) is not list or len(parsed['entries']) != PREFIX_ENTRIES):
        raise ValueError('complete canonical historical128 cache inventory required')
    by_path = {projection.source_file.path: projection for projection in projections}
    if len(projections) != PREFIX_ENTRIES or set(by_path) != set(ORDERED_PATHS[:PREFIX_ENTRIES]):
        raise ValueError('cache requires the exact independently validated prefix projections')
    seen, previous, contexts = set(), None, {}
    for item in parsed['entries']:
        key, saved, _ = ingestion._restart_entry(item)
        if previous is not None and key <= previous:
            raise ValueError('cache keys must be sorted and unique')
        previous = key
        path = item['context']['path']
        projection = by_path.get(path)
        context = ingestion._frontend_cache_context(ingestor._frontends.get('python'), language='python', path=path)
        if (projection is None or path in seen or context is None
                or item['source_cid'] != projection.source_cid or item['ast_cid'] != projection.ast_cid
                or item['ast_payload'] != json.loads(projection.ast_blob.payload_json)
                or item['context'] != ingestion._source_shard_context_payload(context)
                or item['context_cid'] != context.cid):
            raise ValueError('cache member AST/source/path/current context differs from admitted prefix')
        seen.add(path); contexts[path] = context
    if seen != set(by_path):
        raise ValueError('cache omits prefix source/context membership')
    ingestor.shard_cache.hydrate_bundle(raw, expected_cid=anchor['raw_cid_v1'])
    for path, projection in by_path.items():
        record = ingestor.shard_cache.get(projection.source_cid, context=contexts[path])
        if record is None or record.to_dict() != json.loads(projection.ast_blob.payload_json):
            raise ValueError('hydrated historical shard differs from admitted prefix')
    return {'optimized_handoff_cache': True, 'restored_entries': PREFIX_ENTRIES}
