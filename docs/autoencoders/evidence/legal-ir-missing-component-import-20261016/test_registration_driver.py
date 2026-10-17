"""Inert storage-boundary controls, never a substitute for genuine registration.

The historical helper and current driver are real stdlib-only source bodies.
Managers, connections and the orchestration admission seam below are explicitly
authored fixtures.  No test imports ModelManager/DuckDB or opens a database.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import threading
import types

import pytest

HERE = Path(__file__).resolve().parent
OLD = Path("/home/barberb/lift_coding/artifacts/normative-checkpoint-availability-20261006/registration")
OPTIONAL = ("_ipfs_backend", "_datasets_manager", "_filesystem_handler", "_provenance_logger",
            "_artifact_storage", "_storage_wrapper", "_knowledge_graph")


def checked_fixture_module(path, name, monkeypatch, expected=None):
    raw = Path(path).read_bytes()
    if expected is not None:
        assert hashlib.sha256(raw).hexdigest() == expected
    module = types.ModuleType(name)
    module.__file__ = str(path)
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    custody = checked_fixture_module(OLD / "custody.py", "_fixture_registration_custody", monkeypatch,
        "c3b355c2b3e4743a839a721b61c1d2868fe25c609b8da562a6b302fbe0cb6864")
    monkeypatch.setitem(sys.modules, "custody", custody)
    guard = checked_fixture_module(OLD / "register_normative_states.py", "_fixture_retained_registration", monkeypatch,
        "ba8f50acd731ae42ba1883b1289395fdc108e0ece1045b39f8afd0b785598309")
    driver = checked_fixture_module(HERE / "registration_driver.py", "_fixture_current_registration", monkeypatch)
    store = tmp_path / "metadata.duckdb"
    # A selected path only: no database is created, connected or serialized.
    monkeypatch.setattr(driver, "STORE", store)
    return types.SimpleNamespace(driver=driver, guard=guard, store=store)


class NativeMetadata:
    MAX_REFERENCE_BYTES = 1024

    @staticmethod
    def _stable_metadata(row):
        return {key: value for key, value in row.items() if key != "updated_at"}

    @classmethod
    def _matches(cls, actual, expected):
        return cls._stable_metadata(actual) == cls._stable_metadata(expected)


def record(model_id):
    return {"model_metadata": {"model_id": model_id, "architecture": "authored-inert",
        "huggingface_config": {"ir_checkpoint": {"runtime_ready": False}}},
        "checkpoint_pin": {}, "release": {}}


class FixtureConnection:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def inert_manager_class(baseline, persisted, saves, *, constructor_save=False):
    """Model the dangerous genuine behavior: every saved row gets retimestamped."""
    class InertManager:
        instances = []

        def __init__(self, **kwargs):
            self.instances.append(self)
            self._model_lock = threading.RLock()
            self.models = {row["model_id"]: copy.deepcopy(row) for row in baseline}
            self.use_database = kwargs["use_database"]
            self.storage_path = kwargs["storage_path"]
            self.con = FixtureConnection()
            for name in OPTIONAL:
                setattr(self, name, None)
            if constructor_save:
                self._save_data()

        def _save_data(self):
            saves.append(set(self.models))
            for model_id, row in self.models.items():
                saved = copy.deepcopy(row)
                saved["updated_at"] = "rewritten-by-fixture-genuine-save"
                persisted[model_id] = saved

        def add_model(self, metadata):
            self.models[metadata["model_id"]] = copy.deepcopy(metadata)
            self._save_data()
            return True

        def close(self):
            self._save_data()
            self.con.close()

    return InertManager


def test_absent_only_save_preserves_unrelated_and_present_activity(boundary):
    old, present, new = (record(name) for name in ("unrelated", "already-present", "new"))
    baseline = [dict(row["model_metadata"], updated_at="original-activity") for row in (old, present)]
    persisted = {row["model_id"]: copy.deepcopy(row) for row in baseline}
    saves, stages = [], []
    Manager = inert_manager_class(baseline, persisted, saves)
    duckdb = types.SimpleNamespace(DuckDBPyConnection=FixtureConnection)

    class Importer(NativeMetadata):
        @staticmethod
        def import_ir_model_manager_records(pin, *, manager, readback, **kwargs):
            assert stages[0]["models"] == [new]
            assert manager.add_model(new["model_metadata"]) is True
            assert readback("new")["model_id"] == "new"
            return {"completed": True, "registered_count": 1,
                    "already_present_count": 0, "persisted_metadata_matched_count": 1}

    result = boundary.guard.import_missing(Importer, {"schema": "inert", "models": [present, new]}, baseline,
        make_manager=lambda ids: boundary.driver.construct_manager(Manager, NativeMetadata, baseline, ids, duckdb, lambda: None),
        stage_plan=lambda plan: stages.append(plan) or {}, readback=lambda model_id: persisted[model_id],
        releases=[], max_reference_bytes=1024)
    assert result["missing_count"] == result["already_present_count"] == 1
    assert saves == [{"new"}, set()]
    assert persisted["unrelated"] == baseline[0]
    assert persisted["already-present"] == baseline[1]
    assert persisted["new"]["updated_at"] == "rewritten-by-fixture-genuine-save"
    assert Manager.instances[0].models == {}
    assert not boundary.store.exists() and not Path(str(boundary.store) + ".json").exists()


def test_preinit_guard_blocks_full_baseline_save_before_filtering(boundary):
    baseline = [dict(record("old")["model_metadata"], updated_at="keep-me")]
    persisted = {"old": copy.deepcopy(baseline[0])}
    saves = []
    Manager = inert_manager_class(baseline, persisted, saves, constructor_save=True)
    with pytest.raises(ValueError, match="population exceeds absent targets"):
        boundary.driver.construct_manager(Manager, NativeMetadata, baseline, {"new"},
            types.SimpleNamespace(DuckDBPyConnection=FixtureConnection), lambda: None)
    assert saves == []
    assert persisted == {"old": baseline[0]}
    assert Manager.instances[0].models == {}
    assert Manager.instances[0].con.close_calls == 1


@pytest.mark.parametrize("save_inside_init", [True, False], ids=["inside-init", "after-init"])
def test_fallback_ctor_and_cleanup_never_write_json(boundary, save_inside_init):
    fallback = Path(str(boundary.store) + ".json")
    events = []

    class FallbackManager:
        instances = []

        def __init__(self, **kwargs):
            self.instances.append(self)
            self.models = {"baseline": {"model_id": "baseline"}}
            self._model_lock = threading.RLock()
            self.storage_path = kwargs["storage_path"]
            self.use_database = False
            self.con = None
            if save_inside_init:
                self._save_data()

        def _save_data(self):
            events.append("unsafe-json-save")
            fallback.write_text(json.dumps(self.models))

        def close(self):
            events.append("unsafe-manager-close")
            self._save_data()

    with pytest.raises(ValueError, match="fall back to JSON|lost the guarded selected DuckDB"):
        boundary.driver.construct_manager(FallbackManager, NativeMetadata, [], {"new"},
            types.SimpleNamespace(DuckDBPyConnection=FixtureConnection), lambda: None)
    partial = FallbackManager.instances[0]
    boundary.driver.cleanup_manager(partial, types.SimpleNamespace(DuckDBPyConnection=FixtureConnection))
    assert partial.models == {} and events == []
    assert not fallback.exists() and not boundary.store.exists()


def test_early_partial_constructor_cleanup_does_not_call_unsafe_close(boundary):
    events = []

    class PartialManager:
        instances = []

        def __init__(self, **kwargs):
            self.instances.append(self)
            self.models = {"old": {"model_id": "old"}}
            raise RuntimeError("authored early constructor failure")

        def _save_data(self):
            events.append("save")

        def close(self):
            events.append("close")
            Path(str(boundary.store) + ".json").write_text("unsafe fallback")

    with pytest.raises(RuntimeError, match="authored early constructor failure"):
        boundary.driver.construct_manager(PartialManager, NativeMetadata, [], {"new"},
            types.SimpleNamespace(DuckDBPyConnection=FixtureConnection), lambda: None)
    assert PartialManager.instances[0].models == {} and events == []
    assert not Path(str(boundary.store) + ".json").exists()


def test_late_unapproved_population_never_reaches_genuine_save(boundary):
    baseline = [dict(record("old")["model_metadata"], updated_at="keep")]
    persisted = {"old": copy.deepcopy(baseline[0])}
    saves = []
    Manager = inert_manager_class(baseline, persisted, saves)
    duckdb = types.SimpleNamespace(DuckDBPyConnection=FixtureConnection)
    manager = boundary.driver.construct_manager(Manager, NativeMetadata, baseline, {"new"}, duckdb, lambda: None)
    manager.models["old"] = copy.deepcopy(baseline[0])
    try:
        with pytest.raises(ValueError, match="population exceeds absent targets"):
            manager._save_data()
        assert saves == [] and persisted == {"old": baseline[0]}
    finally:
        boundary.driver.cleanup_manager(manager, duckdb)


def test_complete_baseline_gate_rejects_activity_rewrite(boundary):
    before = dict(record("old")["model_metadata"], updated_at="original")
    after = dict(before, updated_at="retimestamped")
    assert NativeMetadata._matches(before, after) is True
    with pytest.raises(ValueError, match="baseline row or activity changed"):
        boundary.guard.check_population(NativeMetadata, [after], [before], {"models": [record("old")]})


def schema_fixture():
    # Authored constructor text is parsed only, never compiled/imported/executed.
    names = ["model_id", "model_name", "model_type", "architecture"] + [f"field_{i:02d}" for i in range(4, 32)]
    table = "CREATE TABLE IF NOT EXISTS model_metadata (\n" + "\n".join(f"    {name} VARCHAR," for name in names) + "\n)"
    declarations = [table, "serving_config", "CREATE INDEX IF NOT EXISTS idx_model_type ON model_metadata(model_type)",
        "CREATE INDEX IF NOT EXISTS idx_architecture ON model_metadata(architecture)",
        "CREATE INDEX IF NOT EXISTS idx_model_name ON model_metadata(model_name)"]
    raw = ("class ModelManager:\n    def _create_database_tables(self):\n" +
           "\n".join("        declaration = " + repr(value) for value in declarations) + "\n").encode()
    schema = {"tables": [["main", "model_metadata"]],
        "columns": [["main", "model_metadata", name, i + 1, "VARCHAR", "YES", None] for i, name in enumerate(names)] +
                   [["main", "model_metadata", "serving_config", 33, "JSON", "YES", None]],
        "indexes": [["main", "model_metadata", "idx_" + column, False, False, "[" + column + "]", "authored inert SQL"]
                    for column in ("model_type", "architecture", "model_name")]}
    return raw, schema


def orchestration_case(boundary, tmp_path, monkeypatch, baseline, plan, *, schema_change=None):
    """Exercise run_request ordering with explicit inert admission/storage seams."""
    driver, guard = boundary.driver, boundary.guard
    raw, schema = schema_fixture()
    manager_source = tmp_path / "manager-fixture.py"
    manager_source.write_bytes(raw)
    manager_pin = driver.capture(manager_source)
    owners = [{"pin": {"path": str(tmp_path / "inert-importer.py")}, "relative_path": "inert_importer.py"},
              {"pin": manager_pin, "relative_path": "ipfs_accelerate_py/model_manager.py"}]
    empty = tmp_path / "empty.json"
    empty.write_text("{}\n")
    placeholder = driver.capture(empty)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    output = attempt / "registration"
    calls = []
    native = types.SimpleNamespace(MAX_REFERENCE_BYTES=1024, _stable_metadata=NativeMetadata._stable_metadata,
        _matches=NativeMetadata._matches, _prepare=lambda *args: (copy.deepcopy(plan), [], None, None))
    scope = types.SimpleNamespace(guard=lambda: None, assert_writable_store=lambda path: None,
                                 snapshot=lambda: {"attempt_directory": str(attempt)})
    monkeypatch.setattr(driver, "checked_module", lambda name, pin: guard if name.endswith("guard") else
                        native if name.endswith("native_importer") else types.SimpleNamespace())
    monkeypatch.setattr(driver, "checkpoint_join", lambda *args: [{"model_id": row["model_metadata"]["model_id"]} for row in plan["models"]])
    monkeypatch.setattr(driver, "review_binding", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "restrict_live_scope", lambda value, pin: value)
    monkeypatch.setattr(driver, "FORBIDDEN", set())
    monkeypatch.setattr(driver, "coherent_backup", lambda *args: calls.append("backup") or pytest.fail("all-present/refused preflight reached backup"))
    monkeypatch.setattr(guard, "selected_source_owners", lambda: owners)
    monkeypatch.setattr(guard, "nested_pins", lambda value: [])
    monkeypatch.setattr(guard, "fence", lambda *args: None)
    monkeypatch.setattr(guard, "environment", lambda: None)
    monkeypatch.setattr(guard, "install_execution_fence", lambda *args: ({}, []))
    observed_schema = copy.deepcopy(schema)
    if schema_change == "column":
        observed_schema["columns"].pop()
    if schema_change == "index":
        observed_schema["indexes"].pop()
    monkeypatch.setattr(guard, "fresh_snapshot", lambda *args, **kwargs: (copy.deepcopy(baseline), copy.deepcopy(observed_schema)))
    monkeypatch.setattr(guard, "exact_catalog", lambda plan: {"fixture": "same detached catalog"})
    class InertLoader:
        refused = {}
        def __init__(self, owners):
            pass
        def find_spec(self, *args, **kwargs):
            return None
        def observations(self):
            return []
    monkeypatch.setattr(driver, "CurrentSources", InertLoader)
    original_import = driver.importlib.import_module
    def imports(name, *args, **kwargs):
        if name == "duckdb":
            return types.SimpleNamespace(DuckDBPyConnection=FixtureConnection)
        if name == "ipfs_accelerate_py.model_manager":
            calls.append("factory")
            pytest.fail("all-present/refused preflight imported a genuine manager")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(driver.importlib, "import_module", imports)
    request = {"schema": driver.REQUEST_SCHEMA, "datasets_root": str(driver.DATASETS), "datasets_head": driver.DATASETS_HEAD,
        "accelerate_root": str(driver.ACCELERATE), "accelerate_head": driver.ACCELERATE_HEAD,
        "store_path": str(driver.STORE), "guard_pin": {"path": str(driver.GUARD), "bytes": 1, "sha256": driver.GUARD_SHA},
        "custody_pin": {"path": str(driver.CUSTODY), "bytes": 1, "sha256": driver.CUSTODY_SHA},
        "plan_pin": placeholder, "release_receipt_pins": [], "authentication_pin": placeholder,
        "review_pin": placeholder, "resource_scope_pin": placeholder, "source_owners": owners,
        "output_directory": str(output)}
    path = tmp_path / "request.json"
    path.write_bytes(driver.wire(request))
    return types.SimpleNamespace(path=path, sha=hashlib.sha256(path.read_bytes()).hexdigest(), output=output,
                                 scope=scope, calls=calls, original_meta_path=list(sys.meta_path))


def invoke_inert(driver, case):
    try:
        return driver.run_request(case.path, case.sha, register=True, registration_scope=case.scope)
    finally:
        sys.meta_path[:] = case.original_meta_path


def test_all_present_orchestration_constructs_no_factory_and_no_backup(boundary, tmp_path, monkeypatch):
    targets = [record(name) for name in ("one", "two", "three")]
    baseline = [dict(row["model_metadata"], updated_at="original") for row in targets]
    case = orchestration_case(boundary, tmp_path, monkeypatch, baseline, {"schema": "inert", "models": targets})
    pin = invoke_inert(boundary.driver, case)
    result = json.loads(Path(pin["path"]).read_bytes())
    assert result["registration"]["manager_constructed"] is False
    assert result["original_store_pin"] is result["backup_pin"] is None
    assert result["before_count"] == result["after_count"] == 3
    assert case.calls == []
    assert json.loads(Path(result["before_records_pin"]["path"]).read_bytes()) == baseline
    assert json.loads(Path(result["after_records_pin"]["path"]).read_bytes()) == baseline
    assert not boundary.store.exists() and not Path(str(boundary.store) + ".json").exists()


def test_late_conflicting_id_refuses_before_factory_or_backup(boundary, tmp_path, monkeypatch):
    targets = [record(name) for name in ("early-absent", "late-conflict", "last-absent")]
    baseline = [dict(targets[1]["model_metadata"], architecture="conflicting", updated_at="retain")]
    case = orchestration_case(boundary, tmp_path, monkeypatch, baseline, {"schema": "inert", "models": targets})
    with pytest.raises(ValueError, match="existing model_id has conflicting metadata"):
        invoke_inert(boundary.driver, case)
    assert case.calls == []
    assert not (case.output / "registration-result.json").exists()
    assert not boundary.store.exists() and not Path(str(boundary.store) + ".json").exists()


@pytest.mark.parametrize("missing", ["column", "index"])
def test_missing_constructor_schema_refuses_before_factory_or_backup(boundary, tmp_path, monkeypatch, missing):
    targets = [record(name) for name in ("one", "two", "three")]
    case = orchestration_case(boundary, tmp_path, monkeypatch, [], {"schema": "inert", "models": targets}, schema_change=missing)
    with pytest.raises(ValueError, match="constructor migration"):
        invoke_inert(boundary.driver, case)
    assert case.calls == []
    assert not (case.output / "registration-result.json").exists()
    assert not boundary.store.exists() and not Path(str(boundary.store) + ".json").exists()
