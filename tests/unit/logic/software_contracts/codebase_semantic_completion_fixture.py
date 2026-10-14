"""Unexecuted authored34-source semantic completion fixture and protocol data.

Targets are source bytes only. Neither qualification tests nor analyzers import
the pytest modules or execute their tests/fixtures. Global graph assertions
cover relationships crossing the three durable preparation page partitions.
"""
from pathlib import Path

REPOSITORY_ID = 'preparation-semantic-completion:authored-34-source-fixture'
CREATED_AT = 1700000000.0
OPERATION_ID = 'semantic-completion-authored34-v1'
SOURCES = {f'a{i:02d}.py':
           ('def step_%02d(value):\n    return value + %d\n' % (i, i + 1)).encode('ascii')
           for i in range(30)}
SOURCES['a00.py'] = b'from a16 import cross_page\ndef service(value):\n    return cross_page(value) + 1\n'
SOURCES['a15.py'] = b'def boundary(value):\n    return value + 15\n'
SOURCES['a16.py'] = b'from a15 import boundary\ndef cross_page(value):\n    return boundary(value) + 1\n'
SOURCES['a29.py'] = b'from a00 import service\ndef late(value):\n    return service(value) + 29\n'
SOURCES['conftest.py'] = (
    b'import pytest\nfrom a16 import cross_page\n'
    b'@pytest.fixture(scope="session")\ndef root_value():\n    return 7\n'
    b'@pytest.fixture\ndef computed(root_value):\n    return cross_page(root_value)\n')
SOURCES['pyproject.toml'] = (
    b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    b'markers = ["integration: authored static qualification fixture"]\naddopts = "-q"\n')
SOURCES['tests/test_cross_page.py'] = (
    b'from a00 import service\ndef test_cross_page(computed):\n    assert service(computed) > 0\n')
SOURCES['tests/test_late.py'] = (
    b'import pytest\nfrom a29 import late\n@pytest.mark.integration\n'
    b'def test_tail(computed):\n    assert late(computed) >= 1\n')
ORDERED_PATHS = tuple(sorted(SOURCES))
PYTHON_PATHS = tuple(path for path in ORDERED_PATHS if path.endswith('.py'))
PAGE_PARTITIONS = (ORDERED_PATHS[:16], ORDERED_PATHS[16:32], ORDERED_PATHS[32:])
TABLE_NAMES = ('source_revisions', 'source_files', 'ast_blobs', 'ast_nodes', 'scopes',
               'symbols', 'imports', 'references', 'calls', 'effects', 'interfaces',
               'diagnostics', 'invalidations')
CALL_RELATIONSHIPS = (
    (('a00.py', 'service'), ('a16.py', 'cross_page')),
    (('a16.py', 'cross_page'), ('a15.py', 'boundary')),
    (('tests/test_late.py', 'test_tail'), ('a29.py', 'late')),
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
    if len(SOURCES) != 34 or len(PYTHON_PATHS) != 33:
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
