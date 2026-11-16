"""A handoff lookup reads one owner without loading workspaces or backlogs."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).absolute().parents[4]
SOURCE = ROOT / "ipfs_datasets_py/logic/autoformal/work_catalog.py"


def catalog():
    spec = importlib.util.spec_from_file_location("_autoformal_catalog_contract", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_component_lookup_is_detached_and_reads_only_the_small_catalog(monkeypatch):
    owner = catalog()
    genuine, reads = owner._read_json, []
    def observed(path):
        reads.append(Path(path))
        return genuine(path)
    monkeypatch.setattr(owner, "_read_json", observed)
    item = owner.component("definition-use-native")
    assert item["id"] == "definition-use-native"
    assert item["path"] == "ipfs_datasets_py/logic/autoformal/legal_corpus_definition_use_native_v2.py"
    assert len(json.dumps(item).encode()) < 8192
    item["apis"].append("detached_test_control")
    assert "detached_test_control" not in owner.component("definition-use-native")["apis"]
    with pytest.raises(KeyError):
        owner.component("not-an-owner")
    assert len(reads) == 3
    assert all(path == SOURCE.parent / "docs/work_catalog.json" for path in reads)


def test_single_component_cli_runs_with_stdlib_and_compact_output():
    code = r"""
import importlib.abc,runpy,sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.partition('.')[0] in {'ipfs_datasets_py','torch','numpy','transformers','pyarrow'}:
            raise AssertionError('catalog imported runtime owner: '+fullname)
sys.meta_path.insert(0,Deny())
source=sys.argv[1]
sys.argv=[source,'--component','definition-use-native']
runpy.run_path(source,run_name='__main__')
"""
    result = subprocess.run([sys.executable,"-I","-S","-B","-c",code,str(SOURCE)],
        capture_output=True,text=True,timeout=20,check=False)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.encode()) < 8192
    assert json.loads(result.stdout)["id"] == "definition-use-native"


def test_current_catalog_checks_without_reading_historical_evidence(monkeypatch):
    owner = catalog()
    genuine, reads = owner._read_json, []
    expected = genuine(SOURCE.parent / "docs/work_catalog.json")
    assert {"definition-use-native", "experimental-gated-conditioning",
            "experimental-journal-inference"} <= {
                item["id"] for item in expected["components"]}
    assert {"autoformal-source-migration-20261019-01", "full-norm-qualified",
            "parent-use-lake-qualified"} <= {
                item["id"] for item in expected["selected_evidence"]}
    assert "ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json" in expected[
        "required_documentation"]
    def observed(path):
        reads.append(Path(path))
        return genuine(path)
    monkeypatch.setattr(owner, "_read_json", observed)
    result = owner.check_catalog(ROOT)
    assert result["valid"], result["errors"]
    assert result["components_checked"] == len(expected["components"])
    assert result["documentation_paths_checked"] == len(expected["required_documentation"])
    assert result["saved_evidence_records"] == len(expected["selected_evidence"])
    assert result["active_task_count"] == 24
    assert result["archived_prototype_records"] == 7
    assert reads == [SOURCE.parent / "docs/work_catalog.json",
                     SOURCE.parent / "docs/BACKLOG.json"]
    assert result["archive_paths_traversed"] == 0
    assert result["registered_owners_imported"] == 0
    assert result["model_or_native_execution"] is False
    assert result["qualification_or_proof_admission_performed"] is False


def test_summary_distinguishes_archived_sources_with_installed_successors(capsys):
    owner = catalog()
    assert owner.main(["--summary"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["archived_prototypes"] == 7
    assert result["archived_unselected_prototypes"] == 1
    assert result["archived_prototypes_with_installed_successors"] == 6


def _save_fixture(root, values, backlog):
    home = root / "ipfs_datasets_py/logic/autoformal"
    (home / "docs/work_catalog.json").write_text(json.dumps(values))
    (home / "docs/BACKLOG.json").write_text(json.dumps(backlog))


@pytest.fixture
def navigation_fixture(tmp_path):
    root = tmp_path / "checkout"
    home = root / "ipfs_datasets_py/logic/autoformal"
    (home / "docs").mkdir(parents=True)
    (home / "fixture_owner.py").write_text("def prepare():\n    return None\n")
    (home / "README.md").write_text("# A finite navigation fixture\n")
    source = "ipfs_datasets_py/logic/autoformal/fixture_owner.py"
    values = {
        "schema": "legal-autoformal-work-catalog/v1",
        "qualification_status_meaning": {"implementation_present": "Source only."},
        "components": [{
            "id": "fixture-owner", "path": source,
            "owner_module": source.removesuffix(".py").replace("/", "."),
            "apis": ["prepare"], "status": "implementation_present",
            "evidence_ids": ["fixture-evidence"],
        }],
        "selected_evidence": [{
            "id": "fixture-evidence", "root": "artifact_workspace",
            "path": "deliberately-unavailable/saved-observation.json",
            "required_for_catalog_check": False,
        }],
        "archived_prototypes": [{
            "id": "fixture-prototype",
            "status": "archived_source_with_installed_canonical_successor",
            "canonical_successor_component_id": "fixture-owner",
            "canonical_successor_path": source,
            "new_canonical_port_qualification": "implementation_present",
        }],
        "known_candidate_relationships": [{
            "canonical_path": source, "evidence_id": "fixture-evidence",
        }],
        "historical_survey_reference": {"evidence_id": "fixture-evidence"},
        "required_documentation": ["ipfs_datasets_py/logic/autoformal/README.md"],
    }
    backlog = {
        "schema": "legal-ir-active-work-items/v1",
        "tasks": [{
            "id": f"LIR-{number:02d}", "depends_on": [],
            "reuse_owners": ["Unregistered free-text ownership description"],
        } for number in range(1, 25)],
    }
    _save_fixture(root, values, backlog)
    return root, values, backlog


def test_explicit_root_supplies_its_own_catalog_and_backlog(navigation_fixture, monkeypatch):
    owner = catalog()
    root, values, backlog = navigation_fixture
    def adjacent_metadata_is_forbidden():
        raise AssertionError("explicit-root check read adjacent catalog")
    monkeypatch.setattr(owner, "load_catalog", adjacent_metadata_is_forbidden)
    genuine, reads = owner._read_json, []
    def observed(path):
        reads.append(Path(path))
        assert Path(path).is_relative_to(root)
        return genuine(path)
    monkeypatch.setattr(owner, "_read_json", observed)
    result = owner.check_catalog(root)
    assert result["valid"], result["errors"]
    assert result["components_checked"] == 1
    assert result["active_task_count"] == 24
    assert len(reads) == 2
    # Preserve the explicit-root boundary when only its backlog changes.
    backlog["tasks"][0]["depends_on"] = ["outside-this-backlog"]
    _save_fixture(root, values, backlog)
    result = owner.check_catalog(root)
    assert not result["valid"]
    assert any("unknown dependency outside-this-backlog" in item for item in result["errors"])
    assert result["active_task_count"] is None


@pytest.mark.parametrize("defect, expected", [
    ("missing-owner", "required canonical owner is missing"),
    ("missing-api", "declared APIs missing: removed_api"),
    ("missing-doc", "required documentation is missing"),
    ("successor-id", "unknown successor component"),
    ("successor-path", "successor path differs"),
    ("successor-status", "successor qualification differs"),
    ("component-evidence", "unknown evidence reference"),
    ("survey-evidence", "unknown historical survey evidence reference"),
    ("candidate-evidence", "unknown candidate evidence reference"),
])
def test_catalog_rejects_broken_navigation_joins(navigation_fixture, defect, expected):
    owner = catalog()
    root, values, backlog = navigation_fixture
    if defect == "missing-owner":
        (root / values["components"][0]["path"]).unlink()
    elif defect == "missing-api":
        values["components"][0]["apis"] = ["removed_api"]
    elif defect == "missing-doc":
        (root / values["required_documentation"][0]).unlink()
    elif defect == "successor-id":
        values["archived_prototypes"][0]["canonical_successor_component_id"] = "unknown-owner"
    elif defect == "successor-path":
        values["archived_prototypes"][0]["canonical_successor_path"] = "other.py"
    elif defect == "successor-status":
        values["archived_prototypes"][0]["new_canonical_port_qualification"] = "not_started"
    elif defect == "component-evidence":
        values["components"][0]["evidence_ids"] = ["unknown-evidence"]
    elif defect == "survey-evidence":
        values["historical_survey_reference"]["evidence_id"] = "unknown-evidence"
    elif defect == "candidate-evidence":
        values["known_candidate_relationships"][0]["evidence_id"] = "unknown-evidence"
    _save_fixture(root, values, backlog)
    result = owner.check_catalog(root)
    assert result["valid"] is False
    assert any(expected in item for item in result["errors"]), result["errors"]


@pytest.mark.parametrize("defect, expected", [
    ("unknown", "unknown dependency LIR-25"),
    ("self", "self dependency"),
    ("cycle", "active task dependency cycle"),
])
def test_catalog_rejects_invalid_backlog_dependencies(navigation_fixture, defect, expected):
    owner = catalog()
    root, values, backlog = navigation_fixture
    if defect == "unknown":
        backlog["tasks"][0]["depends_on"] = ["LIR-25"]
    elif defect == "self":
        backlog["tasks"][0]["depends_on"] = ["LIR-01"]
    else:
        backlog["tasks"][0]["depends_on"] = ["LIR-02"]
        backlog["tasks"][1]["depends_on"] = ["LIR-01"]
    _save_fixture(root, values, backlog)
    result = owner.check_catalog(root)
    assert result["valid"] is False
    assert result["active_task_count"] is None
    assert any(expected in item for item in result["errors"]), result["errors"]


@pytest.mark.parametrize("defect, expected", [
    ("components", "components must be a list of objects"),
    ("dependency-type", "dependencies must be a list of strings"),
])
def test_catalog_reports_malformed_metadata_without_a_traceback(
        navigation_fixture, capsys, defect, expected):
    owner = catalog()
    root, values, backlog = navigation_fixture
    if defect == "components":
        values["components"] = None
    else:
        backlog["tasks"][0]["depends_on"] = {"not": "a list"}
    _save_fixture(root, values, backlog)
    assert owner.main(["--check", "--repo-root", str(root)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is False
    assert any(expected in item for item in result["errors"]), result["errors"]


@pytest.mark.parametrize("declaration", [
    "def inner():\n        return None",
    "async def inner():\n        return None",
    "class inner:\n        pass",
])
def test_catalog_recognizes_explicit_factory_callable_exports_without_importing(
        navigation_fixture, declaration):
    owner = catalog()
    root, values, backlog = navigation_fixture
    source = ("raise AssertionError('catalog must not import this owner')\n"
        "def make():\n    " + declaration + "\n"
        "    states = ()\n    return inner, states\n"
        "public_api, _states = make()\n")
    (root / values["components"][0]["path"]).write_text(source)
    values["components"][0]["apis"] = ["public_api"]
    _save_fixture(root, values, backlog)
    result = owner.check_catalog(root)
    assert result["valid"], result["errors"]
    assert result["registered_owners_imported"] == 0
    assert result["model_or_native_execution"] is False


def test_catalog_recognizes_live_api_positions_in_mixed_ten_slot_factory_export(
        navigation_fixture):
    owner = catalog()
    root, values, backlog = navigation_fixture
    source = """
def make():
    def hidden():
        return None
    def build_live():
        return None
    def load_live():
        return None
    guard = entry = integrity = old_build_v2 = old_load_v2 = old_build_v3 = old_load_v3 = None
    states = ()
    return (guard, entry, integrity, old_build_v2, old_load_v2, old_build_v3,
            old_load_v3, build_live, load_live, states)
(_guard, _entry, _integrity, _build_v2, _load_v2, _build_v3, _load_v3,
 build_live, load_live, _states) = make()
"""
    (root / values["components"][0]["path"]).write_text(source)
    values["components"][0]["apis"] = ["build_live", "load_live"]
    _save_fixture(root, values, backlog)
    assert owner.check_catalog(root)["valid"]
    # Neither an unexported local nor a returned metadata/alias slot is an API.
    for missing in ("hidden", "_states", "_guard"):
        values["components"][0]["apis"] = [missing]
        _save_fixture(root, values, backlog)
        result = owner.check_catalog(root)
        assert not result["valid"]
        assert any("declared APIs missing: " + missing in error for error in result["errors"])


@pytest.mark.parametrize("defect", [
    "uncalled", "unexported", "all-only", "local-rebound", "conditional-local-rebound",
    "local-deleted", "import-rebound", "factory-rebound", "export-rebound",
    "conditional-export-rebound", "arity", "noncallable", "alias", "branch-return",
    "decorated-local", "decorated-factory", "async-factory", "generator-factory",
    "starred-target", "duplicate-target", "duplicate-return", "list-target",
    "call-argument", "call-keyword", "list-return",
    "star-import", "class-nonlocal-rebound", "class-global-rebound",
])
def test_catalog_refuses_unbound_or_ambiguous_factory_api_claims(navigation_fixture, defect):
    owner = catalog()
    root, values, backlog = navigation_fixture
    source = ("def make():\n    def inner():\n        return None\n"
              "    states = ()\n    return inner, states\npublic_api, _states = make()\n")
    if defect == "uncalled":
        source = source.replace("public_api, _states = make()\n", "")
    elif defect == "unexported":
        source = source.replace("def inner():", "def public_api():").replace(
            "    states = ()", "    def returned():\n        return None\n    states = ()").replace(
            "return inner, states", "return returned, states").replace(
            "public_api, _states =", "_returned, _states =")
    elif defect == "all-only":
        source = source.replace("public_api, _states = make()", "__all__ = ['public_api']")
    elif defect in ("local-rebound", "conditional-local-rebound", "local-deleted", "import-rebound"):
        change = {"local-rebound": "    inner = None\n",
                  "conditional-local-rebound": "    if unknown:\n        inner = None\n",
                  "local-deleted": "    del inner\n",
                  "import-rebound": "    import math as inner\n"}[defect]
        source = source.replace("    return inner, states", change + "    return inner, states")
    elif defect == "factory-rebound":
        source = source.replace("public_api, _states", "make = lambda: (None, ())\npublic_api, _states")
    elif defect in ("export-rebound", "conditional-export-rebound"):
        source += ("public_api = None\n" if defect == "export-rebound" else
                   "if unknown:\n    public_api = None\n")
    elif defect == "arity":
        source = source.replace("public_api, _states", "public_api, _states, extra")
    elif defect == "noncallable":
        source = source.replace("return inner, states", "return states, inner")
    elif defect == "alias":
        source = source.replace("    return inner, states", "    alias = inner\n    return alias, states")
    elif defect == "branch-return":
        source = source.replace("    return inner, states", "    if unknown:\n        return inner, states\n    return inner, states")
    elif defect == "decorated-local":
        source = source.replace("    def inner():", "    @replacement\n    def inner():")
    elif defect == "decorated-factory":
        source = "@replacement\n" + source
    elif defect == "async-factory":
        source = source.replace("def make():", "async def make():")
    elif defect == "generator-factory":
        source = source.replace("    return inner, states", "    yield None\n    return inner, states")
    elif defect == "starred-target":
        source = source.replace("public_api, _states", "public_api, *_states")
    elif defect == "duplicate-target":
        source = source.replace("public_api, _states", "public_api, public_api")
    elif defect == "duplicate-return":
        source = source.replace("return inner, states", "return inner, inner")
    elif defect == "list-target":
        source = source.replace("public_api, _states =", "[public_api, _states] =")
    elif defect == "call-argument":
        source = source.replace("= make()", "= make(1)")
    elif defect == "call-keyword":
        source = source.replace("= make()", "= make(flag=True)")
    elif defect == "list-return":
        source = source.replace("return inner, states", "return [inner, states]")
    elif defect == "star-import":
        source += "from replacement import *\n"
    elif defect == "class-nonlocal-rebound":
        source = source.replace("    return inner, states",
            "    class Rebind:\n        nonlocal inner\n        inner = None\n    return inner, states")
    elif defect == "class-global-rebound":
        source += "class Rebind:\n    global public_api\n    public_api = None\n"
    (root / values["components"][0]["path"]).write_text(source)
    values["components"][0]["apis"] = ["public_api"]
    _save_fixture(root, values, backlog)
    result = owner.check_catalog(root)
    assert not result["valid"]
    assert any("declared APIs missing: public_api" in error for error in result["errors"])
    assert result["registered_owners_imported"] == 0


@pytest.fixture
def large_component_metadata():
    return {
        "id": "large-owner", "path": "example/owner.py", "owner_module": "example.owner",
        "ownership_role": "existing_single_owner", "status": "implementation_present",
        "apis": ["prepare"], "evidence_ids": ["fixture-evidence"], "required": True,
        "compatibility_dependency": False, "notes": "full-only notes " * 1000,
        "private_reviewed_live_guard_selected_20261111": {"opaque": "retained history §\n" * 1000},
        "unknown_future_history": {"nested": [{"receipt": "uninterpreted", "mask": 0}]},
    }


def test_component_default_is_compact_and_full_preserves_unknown_detached_history(
        monkeypatch, large_component_metadata):
    owner = catalog()
    record = large_component_metadata
    reads = []
    def observed():
        reads.append("catalog")
        return {"components": [record]}
    monkeypatch.setattr(owner, "load_catalog", observed)
    expected_keys = {"id", "path", "owner_module", "ownership_role", "status", "apis",
                     "evidence_ids", "required", "compatibility_dependency"}
    compact = owner.component(record["id"])
    assert len(reads) == 1 and set(compact) == expected_keys
    assert compact == {key: record[key] for key in expected_keys}
    assert len(json.dumps(compact, indent=2).encode()) < 8192
    compact["apis"].append("detached")
    full = owner.component(record["id"], full=True)
    assert len(reads) == 2 and full == record
    assert len(json.dumps(full).encode()) > 8192
    full["unknown_future_history"]["nested"][0]["receipt"] = "detached"
    assert owner.component(record["id"], full=True) == record
    assert len(reads) == 3
    with pytest.raises(KeyError):
        owner.component("unknown", full=True)
    assert len(reads) == 4


def test_all_current_components_keep_pretty_navigation_below_compact_limit(monkeypatch):
    owner = catalog()
    saved = owner.load_catalog()
    monkeypatch.setattr(owner, "load_catalog", lambda: saved)
    for record in saved["components"]:
        compact = owner.component(record["id"])
        assert len((json.dumps(compact, indent=2, sort_keys=True) + "\n").encode()) < 8192, record["id"]
        assert all(key in record and value == record[key] for key, value in compact.items())


@pytest.mark.parametrize("full", [False, True], ids=["compact", "complete"])
def test_component_cli_explicit_full_preserves_history_using_stdlib_only(
        tmp_path, large_component_metadata, full):
    home = tmp_path / "source-only-cli"
    (home / "docs").mkdir(parents=True)
    script = home / "work_catalog.py"
    script.write_bytes(SOURCE.read_bytes())
    (home / "docs/work_catalog.json").write_text(json.dumps({
        "schema": "legal-autoformal-work-catalog/v1", "components": [large_component_metadata],
    }))
    code = r"""
import importlib.abc,runpy,sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.partition('.')[0] in {'ipfs_datasets_py','torch','numpy','transformers','pyarrow'}:
            raise AssertionError('catalog imported runtime owner: '+fullname)
sys.meta_path.insert(0,Deny())
source=sys.argv[1]
sys.argv=[source,*sys.argv[2:]]
runpy.run_path(source,run_name='__main__')
"""
    args = [sys.executable, "-I", "-S", "-B", "-c", code, str(script),
            "--component", large_component_metadata["id"]]
    if full:
        args.append("--full")
    result = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    if full:
        assert value == large_component_metadata
        assert len(result.stdout.encode()) > 8192
    else:
        assert value["id"] == large_component_metadata["id"]
        assert len(result.stdout.encode()) < 8192
        assert "notes" not in value and "unknown_future_history" not in value


def test_component_full_optin_requires_bool_before_catalog_read(monkeypatch):
    owner = catalog()
    def forbidden():
        raise AssertionError("invalid full option read the catalog")
    monkeypatch.setattr(owner, "load_catalog", forbidden)
    with pytest.raises(TypeError, match="full must be a bool"):
        owner.component("large-owner", full="yes")


def test_full_cli_still_requires_explicit_task_or_component(capsys):
    owner = catalog()
    with pytest.raises(SystemExit) as error:
        owner.main(["--full", "--summary"])
    assert error.value.code == 2
    assert "--full requires --task ID or --component ID" in capsys.readouterr().err
