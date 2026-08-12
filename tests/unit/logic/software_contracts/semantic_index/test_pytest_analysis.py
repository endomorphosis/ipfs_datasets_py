"""Contract tests for non-executing pytest relationship discovery."""

from __future__ import annotations

from ipfs_datasets_py.logic.software_contracts.semantic_index.pytest_analysis import (
    PytestAnalyzer,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RelationType


def test_discovers_source_bound_tests_fixtures_markers_and_config_edges() -> None:
    analysis = PytestAnalyzer(repository_id="repo:example", namespace="pkg").analyze_python(
        '''
import pytest

@pytest.fixture(scope="module", autouse=False, params=["small", "large"])
def database(tmp_path):
    return tmp_path

@pytest.mark.slow
@pytest.mark.usefixtures("database")
@pytest.mark.parametrize("value, expected", [(1, 2), (3, 4)])
def test_answer(database, value, expected):
    assert value + 1 == expected
''',
        path="tests/test_answer.py",
    )
    assert len(analysis.tests) == len(analysis.fixtures) == 1
    test, fixture = analysis.tests[0], analysis.fixtures[0]
    # Parametrized names are not fixture parameters.
    assert test.fixture_parameters == ("database",)
    assert test.all_parameters == ("database", "expected", "value")
    assert test.usefixtures == ("database",)
    assert test.markers == ("slow",)
    assert test.parametrizations == (("expected", "value"),)
    assert test.confidence == fixture.confidence == "exact"
    assert fixture.dependencies == ("tmp_path",)
    assert fixture.scope == "module"
    assert fixture.params == ("large", "small")
    fixture_edges = [edge for edge in analysis.edges if edge.relation == RelationType.USES_FIXTURE]
    fixture_names = {(edge.source_id, edge.metadata["fixture_name"], edge.confidence) for edge in fixture_edges}
    assert (test.symbol_id, "database", "exact") in fixture_names
    assert (fixture.symbol_id, "tmp_path", "conservative") in fixture_names
    # Parametrized argument names must not become fixture dependencies.
    assert not any(edge.metadata["fixture_name"] in {"value", "expected"} for edge in fixture_edges if edge.source_id == test.symbol_id)
    assert all(edge.metadata["source_bound"] is True for edge in fixture_edges)


def test_parametrized_names_are_not_fixtures_unless_independently_supplied() -> None:
    analysis = PytestAnalyzer().analyze_python(
        '''
import pytest

@pytest.fixture
def value():
    return 99

@pytest.mark.parametrize("value", [1, 2])
@pytest.mark.usefixtures("value")
def test_independent(value):
    pass
''',
        path="tests/test_param.py",
    )
    test = analysis.tests[0]
    # Parameter list only has the parametrized name; usefixtures independently supplies it.
    assert test.fixture_parameters == ()
    assert "value" in test.usefixtures
    assert test.fixture_names == ("value",)
    edges = [edge for edge in analysis.edges if edge.relation == RelationType.USES_FIXTURE and edge.source_id == test.symbol_id]
    assert {edge.metadata["fixture_name"] for edge in edges} == {"value"}


def test_marker_values_and_module_class_marks_are_recorded() -> None:
    analysis = PytestAnalyzer().analyze_python(
        '''
import pytest

pytestmark = pytest.mark.module_slow

@pytest.mark.timeout(30)
class TestGroup:
    pytestmark = pytest.mark.class_integration

    @pytest.mark.timeout(10)
    def test_one(self):
        pass
''',
        path="tests/test_marks.py",
    )
    test = analysis.tests[0]
    assert "timeout(10)" in test.markers
    assert "module_slow" in test.module_markers
    assert "class_integration" in test.class_markers or "timeout(30)" in test.class_markers
    assert "timeout(10)" in test.version_markers
    assert "module_slow" in test.version_markers


def test_autouse_and_scoped_same_named_fixtures_resolve_correctly() -> None:
    combined = PytestAnalyzer(repository_id="repo:example").analyze_files({
        "conftest.py": '''
import pytest

@pytest.fixture(autouse=True)
def audit():
    return []

@pytest.fixture
def shared():
    return "root"
''',
        "tests/conftest.py": '''
import pytest

@pytest.fixture
def shared():
    return "tests"
''',
        "tests/test_one.py": "def test_one(shared):\n    pass\n",
        "test_root.py": "def test_root(shared):\n    pass\n",
    })
    fixtures = {item.name + "@" + item.path: item for item in combined.fixtures}
    assert "shared@conftest.py" in fixtures and "shared@tests/conftest.py" in fixtures
    assert fixtures["audit@conftest.py"].autouse is True
    tests = {item.path: item for item in combined.tests}
    in_tests = tests["tests/test_one.py"]
    at_root = tests["test_root.py"]
    edges_for = lambda symbol_id: {
        edge.metadata["fixture_name"]: edge.target_id
        for edge in combined.edges
        if edge.relation == RelationType.USES_FIXTURE and edge.source_id == symbol_id
    }
    # Closer conftest wins for shared; autouse applies to both.
    assert edges_for(in_tests.symbol_id)["shared"] == fixtures["shared@tests/conftest.py"].symbol_id
    assert edges_for(at_root.symbol_id)["shared"] == fixtures["shared@conftest.py"].symbol_id
    assert edges_for(in_tests.symbol_id)["audit"] == fixtures["audit@conftest.py"].symbol_id
    assert edges_for(at_root.symbol_id)["audit"] == fixtures["audit@conftest.py"].symbol_id


def test_conftest_and_ini_configuration_become_receipt_selectable_artifacts() -> None:
    analyzer = PytestAnalyzer(repository_id="repo:example")
    combined = analyzer.analyze_files({
        "tests/conftest.py": 'pytest_plugins = ["plugin_a"]\n\ndef pytest_configure(config):\n    pass\n',
        "tests/test_one.py": "def test_one(): pass\n",
        "outside/test_other.py": "def test_other(): pass\n",
        "pytest.ini": "[pytest]\nmarkers = slow: slow test\n",
    })
    conftest = next(item for item in combined.configurations if item.path == "tests/conftest.py")
    config = next(item for item in combined.configurations if item.path == "pytest.ini")
    assert conftest.values["plugins"] == ("plugin_a",)
    assert conftest.confidence == "conservative"
    assert config.values["markers"] == "slow: slow test"
    in_tests = next(item for item in combined.tests if item.path == "tests/test_one.py")
    outside_test = next(item for item in combined.tests if item.path == "outside/test_other.py")
    test_edges = [edge for edge in combined.edges if edge.source_id == in_tests.symbol_id and edge.relation == RelationType.CONFIGURED_BY]
    assert {edge.target_id for edge in test_edges} == {
        "pytest-config:tests/conftest.py", "pytest-config:pytest.ini"
    }
    outside_edges = [edge for edge in combined.edges if edge.source_id == outside_test.symbol_id and edge.relation == RelationType.CONFIGURED_BY]
    assert {edge.target_id for edge in outside_edges} == {"pytest-config:pytest.ini"}
    assert all(edge.metadata["source_bound"] is True for edge in (*test_edges, *outside_edges))


def test_dynamic_fixture_and_plugin_construction_is_retained_but_not_exact() -> None:
    analysis = PytestAnalyzer().analyze_python(
        '''
import pytest
pytest_plugins = make_plugins()

@pytest.fixture(params=make_params())
def generated(request):
    return request.param

@make_marker()
def test_dynamic(generated):
    pass
''',
        path="tests/conftest.py",
    )
    assert analysis.fixtures[0].confidence == "conservative"
    assert analysis.tests[0].confidence == "conservative"
    assert analysis.configurations[0].confidence == "conservative"
    assert any("dynamic fixture" in message for message in analysis.diagnostics)
    assert any("dynamic pytest_plugins" in message for message in analysis.diagnostics)


def test_malformed_config_is_an_opaque_artifact_instead_of_silent_omission() -> None:
    analysis = PytestAnalyzer().analyze_configuration("[pytest\n", path="pytest.ini")
    assert analysis.configurations[0].confidence == "opaque"
    assert analysis.artifacts[0].confidence == "opaque"
    assert analysis.diagnostics
