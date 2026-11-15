"""Full-release CLI metadata controls using real tiny Parquet files.

Only upstream corpus/model family generation is modeled. Packaging, additive
staging, Parquet decoding and strict metadata intake use their real owners.
No Hub, model, service or production path is used by these controls.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import scripts.ops.legal_data.build_uscode_full_hf_release as cli
from ipfs_datasets_py.logic.autoformal import legal_source_package_intake_v1 as intake
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import fixture_family_rows


def _tiny_cli_directory(monkeypatch, tmp_path):
    laws = tmp_path / "laws.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "ipfs_cid": "fictional-source-cid",
        "title_number": "1", "section_number": "1",
        "text": "A fictional record for the metadata control.",
        "source_url": "https://example.invalid/statute/1/1",
        "date_modified": "2024-09-20", "law_name": "Fictional law",
        "chapter_json": "{}", "citations_json": "[]",
        "subsections_json": "[]", "legislative_history_json": "[]",
    }]), laws)
    output = tmp_path / "release"
    stale = output / "data/graph/edges/part-999999.parquet"
    stale.parent.mkdir(parents=True)
    pq.write_table(pa.table({"unselected_graph_id": ["stale-test-only"]}), stale)
    stale_bytes = stale.read_bytes()
    stale_identity = (stale.stat().st_dev, stale.stat().st_ino)
    families = fixture_family_rows()
    calls = []

    def modeled_family_generation(*, laws_path, limit, checkpoint_dir):
        # Exercise the actual existing Parquet reader without calling any
        # embedding/model pipeline. The resulting release families are the
        # producer's explicitly fictional fixture population.
        loaded = cli.load_laws_rows(laws_path, limit=limit)
        assert laws_path == laws and len(loaded) == 1
        assert loaded[0]["text"] == "A fictional record for the metadata control."
        calls.append((laws_path, limit))
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / "admission_summary.json").write_text(
            json.dumps({"fictional_fixture_only": True}) + "\n", encoding="utf-8")
        return families

    monkeypatch.setattr(cli, "build_family_rows", modeled_family_generation)
    argv = ["--laws-parquet", str(laws), "--output-dir", str(output), "--limit", "1"]
    return output, stale, stale_bytes, stale_identity, calls, argv


def _strict_staged_intake(output):
    metadata = {name: (output / name).read_bytes() for name in intake.FILES}
    manifest = json.loads(metadata["manifest.json"])
    # This is a fictional test acquisition identity, not a remote authentication.
    request = {
        "schema": intake.REQUEST_SCHEMA_V2,
        "repository_id": intake.REPOSITORY,
        "revision": "a" * 40,
        "metadata_profile": intake.METADATA_PROFILE_V2,
        "expected_release_identity": {key: manifest[key] for key in (
            "release_profile", "release_point", "release_root_cid", "source_revision",
            "manifest_digest", "graph_ontology_version", "producer")},
        "expected_graph_population": {family: {
            "files": sum(item["family"] == family for item in manifest["artifacts"]),
            "rows": sum(item["row_count"] for item in manifest["artifacts"]
                        if item["family"] == family),
        } for family in ("graph_nodes", "graph_edges")},
        "files": [{"path_in_repo": name, "bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest()}
                  for name, raw in metadata.items()],
    }
    raw = json.dumps(request, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    report = intake.prepare_source_package_intake_v2(
        raw, metadata, expected_request_sha256=hashlib.sha256(raw).hexdigest())
    intake.validate_source_package_intake_v2(report, raw, metadata,
        expected_request_sha256=hashlib.sha256(raw).hexdigest(),
        expected_report_sha256=intake.source_package_intake_sha256(report))
    return report


def test_default_cli_stages_strict_wire_metadata_and_excludes_stale_graph_shard(monkeypatch, tmp_path):
    output, stale, stale_bytes, identity, calls, argv = _tiny_cli_directory(monkeypatch, tmp_path)
    assert cli.main(argv) == 0
    assert len(calls) == 1
    manifest = json.loads((output / "manifest.json").read_bytes())
    # Baseline selector: the existing unmodified CLI reaches this real staged
    # output using only its old arguments, then fails this assertion.
    assert "wire_metadata" in manifest, "default full-release CLI emitted legacy broad-glob metadata"
    wire = manifest["wire_metadata"]
    assert wire["default_config"] == "publicus-ir-graphrag-v2"
    assert wire["logical_default_config"] == manifest["default_config"] == "publicus-ir-graphrag/v2"
    paths = wire["data_files"][0]["path"]
    declared = sorted(item["relative_path"] for item in manifest["artifacts"]
                      if item["relative_path"].startswith("data/")
                      and item["relative_path"].endswith(".parquet"))
    assert paths == declared and paths
    stale_relative = stale.relative_to(output).as_posix()
    globbed = {path.relative_to(output).as_posix() for path in output.glob("data/**/*.parquet")}
    assert globbed == set(paths) | {stale_relative}
    assert stale_relative not in paths
    assert stale.read_bytes() == stale_bytes and (stale.stat().st_dev, stale.stat().st_ino) == identity
    tables = [pq.ParquetFile(output / path).read(use_threads=False) for path in paths]
    assert all(table.column_names == ["entry_cid", "legal_id", "family", "record_sha256", "record_json"]
               and all(pa.types.is_string(field.type) for field in table.schema) for table in tables)
    rows, arrow_bytes = sum(table.num_rows for table in tables), sum(table.nbytes for table in tables)
    assert wire["num_examples"] == rows and wire["num_bytes"] == arrow_bytes
    infos = json.loads((output / "dataset_infos.json").read_bytes())
    assert set(infos) == {"publicus-ir-graphrag-v2"}
    assert infos["publicus-ir-graphrag-v2"]["splits"]["train"] == {
        "name": "train", "num_examples": rows, "num_bytes": arrow_bytes}
    report = _strict_staged_intake(output)
    assert report["status"] == "selected_wire_metadata_reconciled" and report["issues"] == []
    assert report["count_reconciliation"]["selected_descriptor_paths"] == paths
    assert all(value is False for value in report["authority"].values())
    assert report["source_join"]["bindings"] == []


def test_explicit_legacy_metadata_opt_out_keeps_unselected_files_and_refuses_strict_intake(monkeypatch, tmp_path):
    output, stale, stale_bytes, identity, calls, argv = _tiny_cli_directory(monkeypatch, tmp_path)
    assert cli.main([*argv, "--legacy-metadata-profile"]) == 0
    assert len(calls) == 1
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert "wire_metadata" not in manifest
    assert manifest["default_config"] == "publicus-ir-graphrag/v2"
    assert stale.read_bytes() == stale_bytes and (stale.stat().st_dev, stale.stat().st_ino) == identity
    with pytest.raises(ValueError, match="explicit HF wire declaration"):
        _strict_staged_intake(output)
