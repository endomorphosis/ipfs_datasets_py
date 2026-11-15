"""Real source fixtures exercise CLI reuse without repeating an inventory build."""
import json
from pathlib import Path
import runpy

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inv
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as imp
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_inventory import (
    _build, _release, _row,
)

ROOT = Path(__file__).resolve().parents[4]
CLI = ROOT / "scripts/ops/legal_ir/inventory_pinned_uscode_sources.py"


def _command(source, output, manifest_sha, *, revision="d" * 40):
    return ["--source-root", str(source), "--repo-id", "justicedao/ipfs_uscode",
            "--revision", revision, "--manifest-sha256", manifest_sha,
            "--output-directory", str(output)]


def _fixture(tmp_path):
    fixture = _release(tmp_path / "source")
    # The CLI consumes the declared repository layout, rather than the unit
    # helper's SHA-addressed resolver. These are synthetic fixture bytes only.
    for descriptor, original in zip(fixture.descriptors, fixture.shards):
        target = fixture.manifest_path.parent / descriptor["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.read_bytes())
    inventory = _build(fixture)
    saved = inventory.save(tmp_path / "retained-inventory.json")
    return fixture, inventory, saved


def _reuse(saved, entry_cids):
    args = ["--reuse-inventory", saved["path"], "--inventory-sha256", saved["sha256"],
            "--inventory-bytes", str(saved["bytes"])]
    for cid in entry_cids:
        args.extend(["--select-entry-cid", cid])
    return args


def _main():
    return runpy.run_path(str(CLI), run_name="_ordinary_inventory_cli_test")["main"]


def _forbid_rebuild(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a retained inventory must never be rebuilt")
    monkeypatch.setattr(inv, "build_uscode_source_inventory", forbidden)


def test_retained_cli_uses_original_loader_and_materializer_with_exact_order(tmp_path, monkeypatch):
    fixture, inventory, saved = _fixture(tmp_path)
    _forbid_rebuild(monkeypatch)
    output = tmp_path / "output"
    ids = [_row(3)["entry_cid"], _row(1)["entry_cid"]]
    assert _main()(_command(fixture.manifest_path.parent, output, fixture.root["sha256"])
                   + _reuse(saved, ids)) == 0
    report = json.loads((output / "inventory-report.json").read_bytes())
    selection = json.loads((output / "selected-inputs/inventory-selection.json").read_bytes())
    extraction = json.loads((output / "selected-inputs/import-receipt.json").read_bytes())
    assert report["retained_inventory_reused"] is True
    assert report["source_inventory_rebuilt"] is False
    assert report["inventory"] == saved
    assert not (output / "inventory.json").exists()
    assert selection["entry_cids"] == ids
    expected = {row["entry_cid"]: row for shard in inventory.to_dict()["shards"] for row in shard["rows"]}
    assert report["selected_input_ids"] == [expected[cid]["metadata"]["input_id"] for cid in ids]
    assert [row["entry_cid"] for row in extraction["rows"]] == ids
    for row, original in zip(extraction["rows"], (_row(3), _row(1))):
        artifact = row["extracted_text"]
        assert artifact["bytes"] == len(original["text"].encode("utf-8"))
        assert artifact["sha256"] == expected[row["entry_cid"]]["metadata"]["text_sha256"]
    assert report["source_unchanged"] is True
    assert selection["selected_source_bytes_verified"] is True
    assert selection["unselected_current_shards_reverified"] is False
    assert selection["training_eligible"] is selection["admitted"] is False
    assert report["training_performed"] is report["embedding_inference_performed"] is report["admitted"] is False


def test_default_cli_still_builds_and_saves_the_declared_inventory(tmp_path):
    fixture = _release(tmp_path / "source", shard_rows=[[_row(1)]])
    target = fixture.manifest_path.parent / fixture.descriptors[0]["relative_path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(fixture.shards[0].read_bytes())
    output = tmp_path / "default-output"
    assert _main()(_command(fixture.manifest_path.parent, output, fixture.root["sha256"])) == 0
    report = json.loads((output / "inventory-report.json").read_bytes())
    assert report["summary"]["declared_row_count"] == 1
    assert (output / "inventory.json").is_file()
    assert "retained_inventory_reused" not in report
    assert "selection_receipt" not in report


@pytest.mark.parametrize("failure", ["inventory_hash", "selected_shard", "release_revision"])
def test_retained_cli_refuses_changed_custody_without_rebuild_or_selected_outputs(tmp_path, monkeypatch, failure):
    fixture, inventory, saved = _fixture(tmp_path)
    _forbid_rebuild(monkeypatch)
    output = tmp_path / "refused-output"
    argv = _command(fixture.manifest_path.parent, output, fixture.root["sha256"],
                    revision="e" * 40 if failure == "release_revision" else "d" * 40)
    supplied = dict(saved)
    if failure == "inventory_hash":
        supplied["sha256"] = "0" * 64
    if failure == "selected_shard":
        selected = fixture.manifest_path.parent / fixture.descriptors[0]["relative_path"]
        raw = selected.read_bytes()
        selected.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises((inv.USCodeInventoryError, imp.USCodeImportError)):
        _main()(argv + _reuse(supplied, [_row(1)["entry_cid"]]))
    assert not (output / "selected-inputs").exists()
    assert not (output / "inventory.json").exists()
    assert json.loads((output / "inventory-report.json").read_bytes())["passed"] is False


def test_retained_cli_does_not_reopen_or_claim_unselected_shards(tmp_path, monkeypatch):
    fixture, inventory, saved = _fixture(tmp_path)
    _forbid_rebuild(monkeypatch)
    unselected = fixture.manifest_path.parent / fixture.descriptors[1]["relative_path"]
    unselected.unlink()
    output = tmp_path / "selected-only-output"
    assert _main()(_command(fixture.manifest_path.parent, output, fixture.root["sha256"])
                   + _reuse(saved, [_row(1)["entry_cid"]])) == 0
    selection = json.loads((output / "selected-inputs/inventory-selection.json").read_bytes())
    assert len(selection["selected_shards"]) == 1
    assert selection["selected_shards"][0]["relative_path"] == fixture.descriptors[0]["relative_path"]
    assert selection["unselected_current_shards_reverified"] is False


@pytest.mark.parametrize("case", ["path_only", "hash_only", "bytes_only", "no_selection",
                                 "invalid_hash", "zero_bytes", "excess_bytes", "duplicates", "excess_entries"])
def test_retained_cli_requires_complete_finite_pins_and_unique_selection_before_io(tmp_path, case):
    saved = {"path": str(tmp_path / "absent-inventory"), "sha256": "a" * 64, "bytes": 1}
    options = _reuse(saved, ["sha256:" + "1" * 64])
    if case == "path_only":
        options = options[:2]
    elif case == "hash_only":
        options = ["--inventory-sha256", "a" * 64]
    elif case == "bytes_only":
        options = ["--inventory-bytes", "1"]
    elif case == "no_selection":
        options = _reuse(saved, [])
    elif case == "invalid_hash":
        options = _reuse(dict(saved, sha256="A" * 64), ["one"])
    elif case == "zero_bytes":
        options = _reuse(dict(saved, bytes=0), ["one"])
    elif case == "excess_bytes":
        options = _reuse(dict(saved, bytes=64 * 1024**2 + 1), ["one"])
    elif case == "duplicates":
        options = _reuse(saved, ["one", "one"])
    elif case == "excess_entries":
        options = _reuse(saved, [str(index) for index in range(257)])
    output = tmp_path / "not-created"
    with pytest.raises(SystemExit) as exc:
        _main()(_command(tmp_path / "absent-source-root", output, "b" * 64) + options)
    assert exc.value.code == 2
    assert not output.exists()
