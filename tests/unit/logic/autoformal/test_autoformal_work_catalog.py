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
