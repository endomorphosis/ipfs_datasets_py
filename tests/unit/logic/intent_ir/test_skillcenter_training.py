"""Source provenance, policy, and partition integrity for Intent training."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import skillcenter_training as sut
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import SkillCenterSkillRecord


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fixture(root, records=None):
    root.mkdir()
    if records is None:
        records = [
            ("first", "MIT", "allow", "# Goals\n- Repair the parser.\n# Steps\n- Run the parser checks.\n"),
            ("same-body", "MIT", "allow", "# Goals\n- Repair the parser.\n# Steps\n- Run the parser checks.\n"),
            ("second", "Apache-2.0", "allow", "# Goals\n- Create a fixture.\n# Steps\n- Write a fixture file.\n"),
            ("unknown", "NOASSERTION", "needs_review", "# Goals\n- Inspect the service.\n"),
        ]
    rows = []
    for name, license_, risk, text in records:
        r = SkillCenterSkillRecord(
            skill_id=name, domain="devtools", profile="devtools", source_type="public-source",
            source_url=f"https://clawhub.ai/registry/{name}/1.0.0/SKILL.md", title=name,
            overall_score=2.0, skill_kind="claw-skill", language="en", source_id=name,
            primary_source_id=name, metadata_yaml=f'license_spdx: "{license_}"\nlicense_risk: "{risk}"\n',
            skill_md=text, library_md="", dataset_id="Tommysha/skillcenter-bundles",
            dataset_revision="b" * 40, repository_file="skills.sqlite", bundle_sha256="c" * 64)
        rows.append({**asdict(r), "content_sha256": r.content_sha256, "content_cid": r.content_cid,
                     "entry_cid": r.entry_cid, "entry_sha256": r.entry_identity.sha256,
                     "license_expression": license_, "license_risk": risk})
    shard = root / "data/corpus/part-000000.parquet"
    shard.parent.mkdir(parents=True)
    table = pa.Table.from_pylist(rows).replace_schema_metadata({b"schema_version": b"skillcenter-corpus-row/v1"})
    pq.write_table(table, shard)
    index = root / "indexes/corpus_chunks.parquet"
    index.parent.mkdir()
    pq.write_table(pa.Table.from_pylist([{"relative_path": shard.relative_to(root).as_posix(),
        "sha256": _sha(shard.read_bytes()), "size_bytes": shard.stat().st_size, "row_count": len(rows)}]), index)
    manifest = {"schema_version": "skillcenter-huggingface-release/v3",
                "dataset_repo_id": "Publicus/skillcenter-ir", "dataset_id": "Tommysha/skillcenter-bundles",
                "dataset_revision": "b" * 40, "indexes": {"corpus_chunks": {
                    "relative_path": index.relative_to(root).as_posix(), "sha256": _sha(index.read_bytes()),
                    "size_bytes": index.stat().st_size}}}
    raw = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(raw)
    return {"release_root": root, "release_revision": "a" * 40,
            "expected_manifest_sha256": _sha(raw), "shards": [shard.relative_to(root).as_posix()]}


def test_pinned_export_keeps_source_and_duplicate_family_fences(tmp_path):
    args = _fixture(tmp_path / "release")
    descriptor = sut.export_skillcenter_training_corpus(**args, output=tmp_path / "out")
    report = sut.load_skillcenter_training_corpus(descriptor)
    assert report["counts"]["scanned_rows"] == 4
    assert report["counts"]["source_eligible_rows"] == 3
    assert report["counts"]["release_license_review_rows"] == 1
    assert report["gold_formal_target_count"] == 0
    assert not report["qualified"] and not report["admitted"]
    samples = {r["source_record"]["skill_id"]: r for r in report["samples"]}
    assert samples["first"]["split"] == samples["same-body"]["split"]
    assert all(_sha(r["instruction"].encode()) == r["source_sha256"] for r in samples.values())
    assert report["producer_sha256"]
    assert all(not r["native_weak_targets"]["qualified"] for r in samples.values())


@pytest.mark.parametrize("revision", ["main", "latest", "a" * 39, "A" * 40])
def test_mutable_or_malformed_revision_rejected(tmp_path, revision):
    args = _fixture(tmp_path / "release")
    args["release_revision"] = revision
    with pytest.raises(ValueError, match="immutable"):
        sut.export_skillcenter_training_corpus(**args, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_source_change_invalidates_existing_export(tmp_path):
    args = _fixture(tmp_path / "release")
    descriptor = sut.export_skillcenter_training_corpus(**args, output=tmp_path / "out")
    (args["release_root"] / args["shards"][0]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        sut.load_skillcenter_training_corpus(descriptor)


def test_forged_export_authority_rejected_even_with_updated_outer_hash(tmp_path):
    args = _fixture(tmp_path / "release")
    descriptor = sut.export_skillcenter_training_corpus(**args, output=tmp_path / "out")
    path = Path(descriptor["path"])
    report = json.loads(path.read_bytes())
    report["qualified"] = True
    raw = json.dumps(report).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="pinned native replay"):
        sut.load_skillcenter_training_corpus({**descriptor, "sha256": _sha(raw)})


def test_native_policy_rechecked_not_just_release_license_flag(tmp_path):
    args = _fixture(tmp_path / "release", records=[("fake-allow", "NOASSERTION", "allow", "# Goals\n- Build a report.\n")])
    descriptor = sut.export_skillcenter_training_corpus(**args, output=tmp_path / "out")
    report = sut.load_skillcenter_training_corpus(descriptor)
    assert report["counts"]["native_policy_excluded_rows"] == 1
    assert report["samples"] == []


def test_registry_versions_group_and_distinct_packages_do_not_merge():
    assert sut._repository_group("https://clawhub.ai/registry/parser/1.0.0/SKILL.md") == sut._repository_group("https://clawhub.ai/registry/parser/2.0.0/SKILL.md")
    assert sut._repository_group("https://clawhub.ai/registry/parser/1/SKILL.md") != sut._repository_group("https://clawhub.ai/registry/other/1/SKILL.md")


@pytest.mark.parametrize("max_examples", [False, 0, 513])
def test_export_budget_checked_before_writing(tmp_path, max_examples):
    args = _fixture(tmp_path / "release")
    with pytest.raises(ValueError, match="max_examples"):
        sut.export_skillcenter_training_corpus(**args, max_examples=max_examples, output=tmp_path / "out")


def test_output_cannot_replace_an_existing_model_directory(tmp_path):
    args = _fixture(tmp_path / "release")
    existing = tmp_path / "legal-model"
    existing.mkdir()
    (existing / "weights.json").write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh"):
        sut.export_skillcenter_training_corpus(**args, output=existing)
    assert (existing / "weights.json").read_bytes() == b"preserve"


def _cli():
    path = Path(__file__).resolve().parents[4] / "scripts/training/train_intent_autoencoder.py"
    spec = importlib.util.spec_from_file_location("intent_training_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_rejects_training_budget_before_opening_corpus(tmp_path):
    with pytest.raises(ValueError, match="limited to"):
        _cli().main(["train", "--corpus-descriptor", str(tmp_path / "absent.json"),
                     "--epochs", "9", "--output", str(tmp_path / "output")])


def test_cli_export_train_and_load_real_shared_weights(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    nouns = ["database", "renderer", "scheduler", "storage", "catalog", "headers", "cookies",
             "filesystem", "registry", "parser", "serializer", "allocator", "network", "search",
             "queue", "screen", "cache", "archive", "editor", "metrics", "gateway", "adapter",
             "routing", "session", "logging", "tracing", "index", "compiler", "resolver", "stream"]
    rows = [(name, "MIT", "allow", f"Inspect {name} behavior and describe {name} requirements.") for name in nouns]
    args = _fixture(tmp_path / "release", records=rows)
    cli = _cli()
    assert cli.main(["export", "--release-root", str(args["release_root"]),
                     "--release-revision", args["release_revision"],
                     "--manifest-sha256", args["expected_manifest_sha256"],
                     "--shard", args["shards"][0], "--output", str(tmp_path / "corpus")]) == 0
    descriptor = json.loads(capsys.readouterr().out)
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text(json.dumps(descriptor))
    before = descriptor_path.read_bytes()
    assert cli.main(["train", "--corpus-descriptor", str(descriptor_path), "--epochs", "1",
                     "--latent-width", "2", "--output", str(tmp_path / "intent-model")]) == 0
    receipt = json.loads(capsys.readouterr().out)
    from ipfs_datasets_py.logic.intent_ir.formalize.preplanning import load_intent_feature_checkpoint
    loaded = load_intent_feature_checkpoint(receipt["checkpoint"])
    assert loaded["state"]["completed_epochs"] == 1
    assert receipt["selected_split_counts"]["train"] > 0
    assert receipt["selected_split_counts"]["validation"] > 0
    assert receipt["test_used_for_training_or_tuning"] is False
    assert receipt["natural_language_logic_decoder_trained"] is False
    assert receipt["inference_feature_producer_sha256"]
    assert descriptor_path.read_bytes() == before


def test_cli_feature_preflight_excludes_bad_inputs_without_reassigning_splits():
    cli = _cli()
    def fail(_):
        raise ValueError("private source body must not appear in the receipt")
    targets, selected, observations = cli._preflight([
        {"id": "sample", "split": "validation", "instruction": "body"}], fail, fail)
    assert all(not rows for rows in targets.values())
    assert all(not rows for rows in selected.values())
    assert observations == [{"source_id": "sample", "split": "validation",
        "status": "excluded_prompt_adapter_or_feature_validation", "error_type": "ValueError"}]
