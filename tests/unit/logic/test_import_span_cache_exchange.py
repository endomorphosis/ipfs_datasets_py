"""Portable import keeps full evidence without transferring execution authority."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts/ops/legal_ir/import_span_cache_exchange.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "import_span_cache_exchange_tested", _SCRIPT
)
importer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(importer)


def _row(label="one", *, dependencies=(), packet_text="source", task_updates=None):
    packet = {
        "schema": "repair/v1",
        "admitted": False,
        "formalized": False,
        "source": packet_text,
    }
    raw = importer._json(packet)
    task = {
        "task_id": label,
        "acceptance": "Keep the original exception and temporal constraint.",
        "title": "Repair " + label,
        "depends_on": list(dependencies),
        "source_text": packet_text,
        "capture": {"loss": 0.125},
    }
    task.update(task_updates or {})
    return {
        "record_kind": "repair_packet",
        "packet_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "packet_json": raw,
        "task_json": importer._json(task),
        "task_id": label,
        "source_span_id": label,
    }


class Source:
    def __init__(self):
        self.tasks = {}
        self.goals = {}
        self.plans = {}
        self.calls = []

    def get(self, key):
        return self.tasks.get(key)

    def get_goal(self, key):
        return self.goals.get(key)

    def get_plan(self, key):
        return self.plans.get(key)

    def materialize(self, population):
        self.calls.append(copy.deepcopy(population))
        for item in population["goals"]:
            assert item["goal_cid"] not in self.goals
            self.goals[item["goal_cid"]] = {
                "body": dict(item),
                "status": item["status"],
                "revision": 1,
                "goal_cid": item["goal_cid"],
            }
        for item in population["plans"]:
            assert item["plan_cid"] not in self.plans
            self.plans[item["plan_cid"]] = {
                "body": dict(item),
                "status": item["status"],
                "revision": 1,
                "plan_cid": item["plan_cid"],
            }
        for item in population["tasks"]:
            assert item["task_cid"] not in self.tasks
            self.tasks[item["task_cid"]] = SimpleNamespace(
                body=dict(item),
                status=item["status"],
                revision=1,
                task_cid=item["task_cid"],
                goal_cid=item["goal_cid"],
                dependencies=tuple(item["depends_on"]),
            )


def test_exact_context_is_preserved_without_accepting_dataset_execution(tmp_path):
    row = _row(
        packet_text="large evidence " * 25000,
        task_updates={
            "validation_commands": [{"argv": ["touch", "/tmp/DO_NOT_EXECUTE"]}],
            "outputs": [{"path": "ipfs_datasets_py/logic/unsafe.py"}],
            "review_only": False,
            "is_schedulable": True,
            "status": "completed",
        },
    )
    plan = importer.plan_import([row])
    source = Source()
    receipt = importer.materialize_import(
        source,
        plan,
        packet_directory=tmp_path / "packets",
        origin={"revision": "a" * 40, "census_sha256": "b" * 64},
    )
    native = next(iter(source.tasks.values()))
    assert receipt["inserted_count"] == 1 and receipt["executed"] is False
    assert native.status == "blocked"
    assert native.body["review_only"] is True
    assert native.body["is_schedulable"] is False
    assert native.body["validation_commands"] == [] and native.body["outputs"] == []
    assert Path(native.body["packet_path"]).read_text() == row["packet_json"]
    assert Path(native.body["exported_task_path"]).read_text() == row["task_json"]
    assert native.body["acceptance_criteria"] == [
        json.loads(row["task_json"])["acceptance"]
    ]
    assert "Verified census and manifest" in native.body["body_markdown"]
    assert len(importer._json(native.body)) < 10_000


@pytest.mark.parametrize(
    "status", ["blocked", "ready", "claimed", "in_progress", "completed", "failed"]
)
def test_replay_preserves_every_lifecycle_and_goal_revision(tmp_path, status):
    row = _row()
    plan = importer.plan_import([row])
    source = Source()
    importer.materialize_import(
        source, plan, packet_directory=tmp_path / "one", origin={}
    )
    native = next(iter(source.tasks.values()))
    native.status, native.revision = status, 17
    native.body["completion_receipt"] = {"evidence": "preserve me"}
    source.goals[native.goal_cid]["status"] = "completed"
    source.goals[native.goal_cid]["revision"] = 8
    native_plan = source.plans[native.body["plan_cid"]]
    native_plan["status"], native_plan["revision"] = "superseded", 9
    before = copy.deepcopy(source.__dict__)
    result = importer.materialize_import(
        source, plan, packet_directory=tmp_path / "other", origin={}
    )
    assert result["inserted_count"] == 0
    assert result["existing"] == [
        {"task_cid": native.task_cid, "status": status, "revision": 17}
    ]
    assert source.__dict__ == before
    assert not (tmp_path / "other").exists()


def test_conflict_is_checked_for_whole_batch_before_native_writes(tmp_path):
    source = Source()
    old = _row("old", packet_text="old")
    importer.materialize_import(
        source,
        importer.plan_import([old]),
        packet_directory=tmp_path / "old",
        origin={},
    )
    conflict = {
        **old,
        "task_json": importer._json({"task_id": "old", "acceptance": "weaker"}),
    }
    before = copy.deepcopy(source.__dict__)
    new = _row("new", packet_text="new")
    with pytest.raises(importer.ImportError, match="task_sha256"):
        importer.materialize_import(
            source,
            importer.plan_import([new, conflict]),
            packet_directory=tmp_path / "new",
            origin={},
        )
    assert source.__dict__ == before
    assert not (tmp_path / "new").exists()


def test_duplicate_identity_rejects_different_exported_todo():
    first = _row()
    second = {**first, "task_json": importer._json({"task_id": "changed"})}
    with pytest.raises(importer.ImportError, match="conflicting"):
        importer.plan_import([first, second])


def test_all_native_body_bounds_checked_before_any_db_mutation(tmp_path):
    rows = [
        _row("normal", packet_text="normal"),
        _row(
            "oversize",
            packet_text="oversize",
            task_updates={"acceptance": "strict " * 40000},
        ),
    ]
    source = Source()
    with pytest.raises(importer.ImportError, match="body bound"):
        importer.materialize_import(
            source, importer.plan_import(rows), packet_directory=tmp_path, origin={}
        )
    assert source.calls == [] and source.tasks == {} and source.goals == {}


def test_missing_or_modified_retained_evidence_rejects_replay(tmp_path):
    source = Source()
    plan = importer.plan_import([_row()])
    importer.materialize_import(source, plan, packet_directory=tmp_path, origin={})
    native = next(iter(source.tasks.values()))
    Path(native.body["packet_path"]).write_text("modified")
    with pytest.raises(importer.ImportError, match="immutable evidence"):
        importer.materialize_import(source, plan, packet_directory=tmp_path, origin={})
    assert len(source.calls) == 1


def test_shards_assign_dependency_components_once_and_order_independently():
    rows = [
        _row("a", packet_text="a"),
        _row("b", packet_text="b", dependencies=["a"]),
        _row("c", packet_text="c"),
    ]
    shards = [
        importer.plan_import(rows, shard_count=5, shard_index=i) for i in range(5)
    ]
    entries = [entry for shard in shards for entry in shard["entries"]]
    assert len(entries) == 3
    a = next(e for e in entries if e["source_span_id"] == "a")
    b = next(e for e in entries if e["source_span_id"] == "b")
    assert a["assigned_shard"] == b["assigned_shard"]
    assert b["dependencies"] == [a["task_cid"]]
    assert shards == [
        importer.plan_import(list(reversed(rows)), shard_count=5, shard_index=i)
        for i in range(5)
    ]


@pytest.mark.parametrize(
    "rows,pattern",
    [
        ([_row("a", dependencies=["missing"])], "missing or ambiguous"),
        ([_row("a", dependencies=["a"])], "itself"),
        (
            [
                _row("a", packet_text="a", dependencies=["b"]),
                _row("b", packet_text="b", dependencies=["a"]),
            ],
            "cycle",
        ),
    ],
)
def test_dependency_errors_fail_before_any_db_access(rows, pattern):
    with pytest.raises(importer.ImportError, match=pattern):
        importer.plan_import(rows)


def test_packet_byte_tampering_is_rejected():
    row = _row()
    row["packet_json"] += " "
    with pytest.raises(importer.ImportError, match="content hash"):
        importer.plan_import([row])


def test_immutable_revision_required_before_network_access(tmp_path):
    def unexpected(**kwargs):
        pytest.fail("mutable revision triggered network")

    with pytest.raises(importer.ImportError, match="immutable"):
        importer.download_bundle(
            repository_id="x/y",
            revision="main",
            manifest_in_repo="manifest.json",
            staging_directory=tmp_path,
            max_bytes=10000,
            fetch=unexpected,
        )


def test_selective_download_only_requests_manifest_and_exact_two_objects(tmp_path):
    paths = {}
    descriptors = {}
    for kind in ("census", "goals"):
        name = "autoformal/" + kind + "/content.parquet"
        path = tmp_path / name
        path.parent.mkdir(parents=True)
        path.write_bytes((kind + " parquet bytes").encode())
        paths[name] = path
        descriptors[kind] = {
            "path_in_repo": name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"repository_id": "x/y", **descriptors}))
    paths["manifest.json"] = manifest
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return paths[kwargs["filename"]]

    result = importer.download_bundle(
        repository_id="x/y",
        revision="a" * 40,
        manifest_in_repo="manifest.json",
        staging_directory=tmp_path,
        max_bytes=10000,
        fetch=fetch,
    )
    assert result == manifest
    assert [item["filename"] for item in calls] == [
        "manifest.json",
        *[descriptors[k]["path_in_repo"] for k in ("census", "goals")],
    ]
    assert [item["max_size"] for item in calls][1:] == [
        descriptors[k]["bytes"] for k in ("census", "goals")
    ]


def test_download_size_budget_rejected_before_parquet_fetch(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repository_id": "x/y",
                "census": {"path_in_repo": "census.parquet", "bytes": 50000},
            }
        )
    )
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return manifest

    with pytest.raises(importer.ImportError, match="byte bound"):
        importer.download_bundle(
            repository_id="x/y",
            revision="a" * 40,
            manifest_in_repo="manifest.json",
            staging_directory=tmp_path,
            max_bytes=1000,
            fetch=fetch,
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "path",
    ["../file", "/file", "a/../file", "a//file", "a\\file", "sealed-spans.parquet"],
)
def test_repository_traversal_or_protected_files_rejected(path):
    with pytest.raises(importer.ImportError):
        importer._repo_path(path)


def test_existing_receipt_rejected_before_logic_import_network_or_db(
    tmp_path, monkeypatch
):
    (tmp_path / "import-receipt.json").write_text("retained")
    monkeypatch.setattr(
        importer,
        "_pin_logic",
        lambda: pytest.fail("pin reached before receipt collision"),
    )
    with pytest.raises(importer.ImportError, match="already contains"):
        importer.main(
            ["--manifest", str(tmp_path / "unused.json"), "--output", str(tmp_path)]
        )


def test_dry_run_is_default_and_materialization_requires_explicit_native_paths(
    tmp_path,
):
    args = importer.parser().parse_args(
        ["--manifest", "manifest.json", "--output", str(tmp_path)]
    )
    assert args.materialize is False
    with pytest.raises(importer.ImportError, match="requires"):
        importer.main(
            ["--manifest", "manifest.json", "--output", str(tmp_path), "--materialize"]
        )


def test_full_census_is_retained_locally_and_reverified_before_copy(tmp_path):
    sources = {
        kind: tmp_path / (kind + suffix)
        for kind, suffix in (
            ("manifest", ".json"),
            ("census", ".parquet"),
            ("goals", ".parquet"),
        )
    }
    for kind, path in sources.items():
        path.write_bytes((kind + " complete evidence with IR and provenance").encode())
    expected = {
        kind: hashlib.sha256(path.read_bytes()).hexdigest()
        for kind, path in sources.items()
    }
    kept = importer.retain_bundle_evidence(
        manifest_path=sources["manifest"],
        census_path=sources["census"],
        goals_path=sources["goals"],
        directory=tmp_path / "retained",
        max_bytes=10000,
        expected_sha256=expected,
    )
    for kind in sources:
        assert Path(kept[kind]["path"]).read_bytes() == sources[kind].read_bytes()
        assert kept[kind]["sha256"] == expected[kind]
    sources["census"].write_bytes(b"changed after validation")
    with pytest.raises(importer.ImportError, match="changed before evidence retention"):
        importer.retain_bundle_evidence(
            manifest_path=sources["manifest"],
            census_path=sources["census"],
            goals_path=sources["goals"],
            directory=tmp_path / "retained",
            max_bytes=10000,
            expected_sha256=expected,
        )


def _real_bundle(tmp_path):
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import (
        publish_compiled_exchange,
    )

    receipt = publish_compiled_exchange(
        [
            {
                "source_span_id": "import-cli-test-span",
                "legal_id": "usc:test:import",
                "text": "The officer shall retain records.",
                "autoencoder_text": "A different sentence with a lost duty.",
                "decompiled": "",
                "agrees": False,
                "cosine_similarity": 0.2,
                "cross_entropy_loss": 1.0,
                "reconstruction_loss": 0.1,
            }
        ],
        tmp_path / "export",
        upload=False,
        agent_id="import-cli-test",
        code_identity="sha256:import-cli-test",
        model_identity="sha256:synthetic-unit-fixture",
    )
    assert receipt["goal_rows"] > 0
    manifest = Path(receipt["manifest"]["path"])
    assert manifest.is_file()
    return manifest


def test_real_bundle_local_cli_retains_full_census_and_is_dry_run(tmp_path):
    manifest_path = _real_bundle(tmp_path)
    output = tmp_path / "consumer-local"
    assert (
        importer.main(["--manifest", str(manifest_path), "--output", str(output)]) == 0
    )
    receipt = json.loads((output / "import-receipt.json").read_text())
    assert receipt["dry_run"] is True and receipt["materialized"] is False
    assert receipt["selected_tasks"] > 0 and receipt["executed"] is False
    manifest = json.loads(manifest_path.read_text())
    evidence = receipt["origin"]["evidence_bundle"]
    for kind in ("census", "goals"):
        assert evidence[kind]["sha256"] == manifest[kind]["sha256"]
        assert (
            hashlib.sha256(Path(evidence[kind]["path"]).read_bytes()).hexdigest()
            == manifest[kind]["sha256"]
        )
    assert not list(output.rglob("*.duckdb"))


def test_real_bundle_repo_shaped_selective_download_and_cli(tmp_path, monkeypatch):
    import shutil

    manifest_path = _real_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    stage = tmp_path / "stage"
    manifest_repo = manifest["path_in_repo"]
    local_files = {manifest_repo: manifest_path}
    for kind in ("census", "goals"):
        local_files[manifest[kind]["path_in_repo"]] = (
            manifest_path.parent / manifest[kind]["filename"]
        )
    calls = []

    def fetch(*, filename, max_size):
        calls.append(filename)
        source = local_files[filename]
        assert source.stat().st_size <= max_size
        destination = stage / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    real_download = importer.download_bundle

    def simulated_hub_download(**kwargs):
        return real_download(**kwargs, fetch=fetch)

    monkeypatch.setattr(importer, "download_bundle", simulated_hub_download)
    output = tmp_path / "consumer-hub-layout"
    assert (
        importer.main(
            [
                "--manifest-in-repo",
                manifest_repo,
                "--revision",
                "a" * 40,
                "--staging-directory",
                str(stage),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    receipt = json.loads((output / "import-receipt.json").read_text())
    assert calls == [
        manifest_repo,
        manifest["census"]["path_in_repo"],
        manifest["goals"]["path_in_repo"],
    ]
    assert receipt["origin"]["revision"] == "a" * 40
    assert receipt["selected_tasks"] > 0 and receipt["materialized"] is False


def test_real_bundle_tamper_rejected_before_native_database_opens(
    tmp_path, monkeypatch
):
    manifest_path = _real_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    path = manifest_path.parent / manifest["census"]["filename"]
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 1
    path.write_bytes(raw)
    monkeypatch.setattr(
        importer,
        "_pin_accelerate",
        lambda root: pytest.fail("native pin reached after input corruption"),
    )
    database = tmp_path / "must-not-exist.duckdb"
    with pytest.raises(ValueError):
        importer.main(
            [
                "--manifest",
                str(manifest_path),
                "--output",
                str(tmp_path / "rejected"),
                "--materialize",
                "--database",
                str(database),
                "--accelerate-root",
                str(tmp_path / "unused"),
            ]
        )
    assert not database.exists()


def test_manifest_change_between_capture_and_loader_is_rejected(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange

    manifest_path = _real_bundle(tmp_path)
    original = exchange.load_exchange_bundle

    def replaced_manifest(path, **kwargs):
        body = json.loads(Path(path).read_text())
        body["changed_after_initial_capture"] = True
        Path(path).write_text(exchange._json(body))
        return original(path, **kwargs)

    monkeypatch.setattr(exchange, "load_exchange_bundle", replaced_manifest)
    with pytest.raises(importer.ImportError, match="manifest changed between"):
        importer.main(
            ["--manifest", str(manifest_path), "--output", str(tmp_path / "changed")]
        )
    assert not (tmp_path / "changed" / "evidence").exists()


def _paired_bundle(tmp_path, *, disagreement=True):
    from ipfs_datasets_py.logic.autoformal.paired_span_census import (
        FORMAL_FORMAT, build_paired_census, write_paired_census_bundle,
    )
    text = "The agency shall retain records."
    rule = {"modality": "Obligation", "actor": "agency", "action": "retain", "object": "records"}
    source = {"source_span_id": "paired-import-1", "legal_id": "usc:5:1", "text": text,
        "compiler_result": {"compiler_status": "compiled", "rules": [rule], "components": [],
            "compilation_complete": True, "decompiled": text, "roundtrip": True}}
    rows = [{**copy.deepcopy(source), "source_span_id": "paired-capability-2"}]
    if disagreement:
        source["model_formal_outputs"] = [{"family": "typed_deontic", "format": FORMAL_FORMAT,
            "payload": {**rule, "modality": "Prohibition"}, "origin": "autoencoder_guided_compiler",
            "independent": False, "target_conditioned": True, "syntax_status": "not_checked"}]
        source["model_formal_output_provenance"] = {
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "model_identity": "synthetic-test-model", "complete": True}
        rows.append(source)
    bundle = build_paired_census(rows, code_identity="synthetic-test-code",
        model_identity="synthetic-test-model", agent_id="paired-import-test")
    return write_paired_census_bundle(bundle, tmp_path / "paired-export")


def test_paired_bundle_cli_retains_exact_four_files_and_plans_only_native_packets(tmp_path, monkeypatch):
    written = _paired_bundle(tmp_path)
    monkeypatch.setattr(importer, "_pin_accelerate", lambda _: pytest.fail("dry run touched native DB"))
    output = tmp_path / "paired-consumer"
    assert importer.main(["--manifest", written["manifest"]["path"], "--output", str(output)]) == 0
    receipt = json.loads((output / "import-receipt.json").read_text())
    assert receipt["materialized"] is receipt["executed"] is False
    assert receipt["dry_run"] is True
    assert receipt["selected_tasks"] == 1
    assert receipt["deferred_descriptive_goal_count"] == 1
    assert receipt["deferred_descriptive_goals"][0]["record_kind"] == "capability_gap"
    assert receipt["origin"]["bundle_schema"] == importer.PAIRED_MANIFEST_SCHEMA
    kept = receipt["origin"]["evidence_bundle"]
    assert set(kept) == {"manifest", "paired_spans", "goals", "artifacts"}
    for kind, artifact in kept.items():
        assert Path(artifact["path"]).read_bytes() == Path(written[kind]["path"]).read_bytes()
        assert artifact["sha256"] == written[kind]["sha256"]
    assert not list(output.rglob("*.duckdb"))


def test_paired_capability_goal_is_retained_without_inventing_native_packet(tmp_path):
    written = _paired_bundle(tmp_path, disagreement=False)
    output = tmp_path / "capability-consumer"
    importer.main(["--manifest", written["manifest"]["path"], "--output", str(output)])
    receipt = json.loads((output / "import-receipt.json").read_text())
    assert receipt["selected_tasks"] == 0
    assert receipt["deferred_descriptive_goal_count"] == 1
    assert receipt["deferred_descriptive_goals"][0]["reason"] == "retained_without_sealed_native_packet_and_task"
    assert not (output / "packets").exists()


def test_paired_repo_layout_selectively_downloads_all_three_tables(tmp_path, monkeypatch):
    import shutil
    written = _paired_bundle(tmp_path)
    manifest_repo = written["manifest"]["path_in_repo"]
    lookup = {entry["path_in_repo"]: Path(entry["path"])
              for kind, entry in written.items() if kind in {"manifest", *importer.PAIRED_TABLES}}
    stage, output, calls = tmp_path / "hub-stage", tmp_path / "paired-remote", []
    def fetch(*, filename, max_size):
        calls.append(filename)
        source = lookup[filename]
        assert source.stat().st_size <= max_size
        destination = stage / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination
    original = importer.download_bundle
    monkeypatch.setattr(importer, "download_bundle", lambda **kwargs: original(**kwargs, fetch=fetch))
    importer.main(["--manifest-in-repo", manifest_repo, "--revision", "a" * 40,
        "--staging-directory", str(stage), "--output", str(output)])
    assert calls == [manifest_repo, *[written[kind]["path_in_repo"] for kind in importer.PAIRED_TABLES]]
    receipt = json.loads((output / "import-receipt.json").read_text())
    assert receipt["selected_tasks"] == 1 and receipt["materialized"] is False


def test_paired_artifact_corruption_rejected_before_native_database_access(tmp_path, monkeypatch):
    written = _paired_bundle(tmp_path)
    path = Path(written["artifacts"]["path"])
    raw = bytearray(path.read_bytes()); raw[len(raw) // 2] ^= 1; path.write_bytes(raw)
    monkeypatch.setattr(importer, "_pin_accelerate", lambda _: pytest.fail("corrupt paired artifact reached native DB"))
    with pytest.raises(ValueError):
        importer.main(["--manifest", written["manifest"]["path"], "--output", str(tmp_path / "rejected"),
            "--materialize", "--database", str(tmp_path / "never.duckdb"),
            "--accelerate-root", str(tmp_path / "unused")])
    assert not (tmp_path / "never.duckdb").exists()


def test_paired_native_replay_requires_all_four_retained_artifacts(tmp_path):
    written = _paired_bundle(tmp_path)
    from ipfs_datasets_py.logic.autoformal.paired_span_census import load_paired_census_bundle
    loaded = load_paired_census_bundle(written["manifest"]["path"])
    kept = importer.retain_bundle_evidence(manifest_path=Path(written["manifest"]["path"]),
        **{kind + "_path": Path(written[kind]["path"]) for kind in importer.PAIRED_TABLES},
        directory=tmp_path / "retained-paired", max_bytes=importer.DEFAULT_MAX_BYTES,
        expected_sha256={kind: written[kind]["sha256"] for kind in ("manifest", *importer.PAIRED_TABLES)})
    origin = {"bundle_schema": importer.PAIRED_MANIFEST_SCHEMA, "evidence_bundle": kept}
    source = Source()
    plan = importer.plan_import(loaded["portable_goal_rows"])
    importer.materialize_import(source, plan, packet_directory=tmp_path / "packets", origin=origin)
    assert len(source.calls) == 1
    result = importer.materialize_import(source, plan, packet_directory=tmp_path / "replay", origin=origin)
    assert result["inserted_count"] == 0
    Path(kept["artifacts"]["path"]).unlink()
    with pytest.raises(importer.ImportError, match="lost its verified"):
        importer.materialize_import(source, plan, packet_directory=tmp_path / "replay", origin=origin)
    assert len(source.calls) == 1


def test_incomplete_paired_retention_closure_rejected(tmp_path):
    with pytest.raises(importer.ImportError, match="exactly three"):
        importer.retain_bundle_evidence(manifest_path=tmp_path / "manifest.json",
            paired_spans_path=tmp_path / "paired.parquet", goals_path=tmp_path / "goals.parquet",
            directory=tmp_path / "retained", max_bytes=1000, expected_sha256={})
