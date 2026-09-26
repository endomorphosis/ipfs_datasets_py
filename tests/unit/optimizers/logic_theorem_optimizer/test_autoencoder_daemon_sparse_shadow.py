"""Full immutable checkpoint endpoints, no training or owner authority."""
import json
from pathlib import Path
import stat

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation_contracts import describe
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch


def fixture(tmp_path, *, base_format="compact", final_format="compact", mutate=True):
    base = ModalAutoencoderTrainingState()
    base.feature_embedding_weights["old"] = [0.5, -0.0]
    base.applied_todo_ids.extend(["before", "before"])
    final = base.copy()
    final._state_identity_tracker.restore_revision(base.state_revision)
    if mutate:
        final.feature_embedding_weights.pop("old")
        final.feature_embedding_weights["new"] = [1.0, -0.0]
        final.legal_ir_view_logits["deontic.ir"] = 0.25
        final.applied_todo_ids.append("after")
    refs = []
    for name, state, kind in (("base", base, base_format), ("final", final, final_format)):
        path = tmp_path / name
        path.write_bytes((state.to_json()+"\n").encode() if kind == "json" else
                         serialize_checkpoint(state, metadata={"endpoint": name, "binding": "synthetic"},
                                              metric_lineage={"profile": "synthetic-v1"}))
        refs.append(describe(path))
    output = tmp_path / "output"
    output.mkdir()
    return (*refs, output)


@pytest.mark.parametrize("base_format,final_format", [("compact", "compact"), ("json", "compact"), ("json", "json")])
def test_full_endpoints_reconstruct_without_changing_source_or_authority(tmp_path, base_format, final_format):
    base, final, output = fixture(tmp_path, base_format=base_format, final_format=final_format)
    before = {r["path"]: Path(r["path"]).read_bytes() for r in (base, final)}
    result = shadow.write_checkpoint_shadow(base, final, base_version_id="registered-base", output_directory=output,
                                            provenance={"case": "synthetic complete-state endpoint"})
    assert result["passed"] and result["mode"] == "diagnostic_only"
    assert all(result["checks"].values())
    assert result["full_checkpoint_authoritative"]
    assert not result["registered_base_authority_verified"]
    assert not result["optimizer_acceptance_asserted"]
    assert not result["intermediate_mutations_replayed"]
    assert not result["admitted"] and not result["promoted"] and not result["publication_performed"]
    assert {r["path"]: Path(r["path"]).read_bytes() for r in (base, final)} == before
    patch = decode_patch(Path(result["patch_ref"]["path"]).read_bytes())
    assert patch.base_version_id == "registered-base" and patch.sequence == 0
    assert patch.provenance["final_artifact"] == {k: final[k] for k in ("sha256", "bytes")}
    saved = json.loads(Path(result["receipt_ref"]["path"]).read_text())
    assert saved == {k: v for k, v in result.items() if k != "receipt_ref"}
    if final_format == "compact":
        assert result["regenerated_compact_checkpoint"] == {k: final[k] for k in ("sha256", "bytes")}
    else:
        assert result["regenerated_compact_checkpoint"] is None
        assert "compact_final_bytes_exact" not in result["checks"]


def test_unchanged_state_is_explicitly_empty_patch(tmp_path):
    base, final, output = fixture(tmp_path, mutate=False)
    result = shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    patch = decode_patch(Path(result["patch_ref"]["path"]).read_bytes())
    assert patch.patch.rows == patch.patch.components == ()
    assert result["capture_report"]["changed_components"] == []
    assert result["capture_report"]["revision_only"] is False


@pytest.mark.parametrize("endpoint", [0, 1])
def test_changed_source_descriptor_is_refused_before_output(tmp_path, endpoint):
    base, final, output = fixture(tmp_path)
    ref = (base, final)[endpoint]
    Path(ref["path"]).write_bytes(Path(ref["path"]).read_bytes() + b"tampered")
    with pytest.raises(ValueError):
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert not list(output.iterdir())


def test_compact_metadata_reserialization_cannot_be_skipped(tmp_path, monkeypatch):
    base, final, output = fixture(tmp_path)
    original = shadow.serialize_checkpoint
    def wrong_metadata(state, **kwargs):
        return original(state, **{**kwargs, "metadata": {"wrong": True}})
    monkeypatch.setattr(shadow, "serialize_checkpoint", wrong_metadata)
    with pytest.raises(shadow.SparseShadowError, match="compact checkpoint bytes"):
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert not list(output.iterdir())


def test_partial_replay_cannot_pass_complete_state_check(tmp_path, monkeypatch):
    base, final, output = fixture(tmp_path)
    original = shadow.replay_patch
    def incomplete(state, *args, **kwargs):
        report = original(state, *args, **kwargs)
        state.applied_todo_ids.pop()
        return report
    monkeypatch.setattr(shadow, "replay_patch", incomplete)
    with pytest.raises(shadow.SparseShadowError, match="complete raw native state"):
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert not list(output.iterdir())


def test_no_overwrite_or_implicit_retry(tmp_path):
    base, final, output = fixture(tmp_path)
    shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(shadow.SparseShadowError, match="empty directory"):
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_failure_during_publication_leaves_no_passing_receipt(tmp_path, monkeypatch):
    base, final, output = fixture(tmp_path)
    def fail_receipt(path, value):
        assert path.name == "receipt.json" and value["passed"] is True
        raise OSError("synthetic receipt failure")
    monkeypatch.setattr(shadow, "_publish_receipt", fail_receipt)
    with pytest.raises(OSError, match="synthetic receipt failure"):
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert (output / "patch.json").is_file()
    assert not (output / "receipt.json").exists()


@pytest.mark.parametrize("failure_stage", ["file_fsync", "directory_fsync"])
def test_late_publication_failure_removes_own_complete_receipt(tmp_path, monkeypatch, failure_stage):
    base, final, output = fixture(tmp_path)
    receipt = output / "receipt.json"
    original_fsync = shadow.os.fsync
    primary = OSError(f"synthetic late {failure_stage} failure")
    observed_complete_receipts = []

    def fail_after_content_write(fd):
        info = shadow.os.fstat(fd)
        selected = (stat.S_ISREG(info.st_mode) if failure_stage == "file_fsync"
                    else stat.S_ISDIR(info.st_mode))
        if selected and receipt.exists() and not observed_complete_receipts:
            if failure_stage == "file_fsync":
                current = receipt.stat()
                assert (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino)
            saved = json.loads(receipt.read_text())
            assert saved["passed"] is True
            observed_complete_receipts.append(saved)
            raise primary
        return original_fsync(fd)

    monkeypatch.setattr(shadow.os, "fsync", fail_after_content_write)
    with pytest.raises(OSError) as caught:
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert caught.value is primary
    assert len(observed_complete_receipts) == 1
    assert (output / "patch.json").is_file()
    assert not receipt.exists()


def test_publication_failure_preserves_replacement_receipt_path(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    moved_original = tmp_path / "original-receipt.open"
    replacement = b'{"unrelated_replacement":true}'
    original_fsync = shadow.os.fsync
    primary = OSError("synthetic replacement during file fsync")
    replaced = False

    def replace_then_fail(fd):
        nonlocal replaced
        if stat.S_ISREG(shadow.os.fstat(fd).st_mode) and not replaced:
            assert json.loads(receipt.read_text())["passed"] is True
            receipt.rename(moved_original)
            receipt.write_bytes(replacement)
            replaced = True
            raise primary
        return original_fsync(fd)

    monkeypatch.setattr(shadow.os, "fsync", replace_then_fail)
    with pytest.raises(OSError) as caught:
        shadow._publish_receipt(receipt, {"passed": True, "synthetic_fixture": True})
    assert caught.value is primary and replaced
    assert receipt.read_bytes() == replacement
    assert json.loads(moved_original.read_text())["passed"] is True
    assert any("replaced" in note for note in caught.value.__notes__)


def test_publication_cleanup_failure_keeps_primary_and_records_cleanup_note(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    original_fsync, original_unlink = shadow.os.fsync, Path.unlink
    primary = OSError("synthetic file fsync failure")

    def fail_file_fsync(fd):
        if stat.S_ISREG(shadow.os.fstat(fd).st_mode):
            assert json.loads(receipt.read_text())["passed"] is True
            raise primary
        return original_fsync(fd)

    def fail_own_unlink(path, *args, **kwargs):
        if path == receipt:
            raise PermissionError("synthetic cleanup denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(shadow.os, "fsync", fail_file_fsync)
    monkeypatch.setattr(Path, "unlink", fail_own_unlink)
    with pytest.raises(OSError) as caught:
        shadow._publish_receipt(receipt, {"passed": True, "synthetic_fixture": True})
    assert caught.value is primary
    assert any("cleanup failed: PermissionError" in note for note in caught.value.__notes__)
    # Cleanup can itself be denied: a file alone is not successful publication.
    # The API must propagate the original failure and expose that limitation.
    assert receipt.exists()


@pytest.mark.parametrize("kind", ["float32", "sparse_manifest"])
def test_non_full_or_lossy_endpoints_are_refused(tmp_path, kind):
    base, final, output = fixture(tmp_path)
    path = Path(final["path"])
    if kind == "float32":
        path.write_bytes(serialize_checkpoint(ModalAutoencoderTrainingState(), float_precision="float32"))
    else:
        path.write_text(json.dumps({"schema": "sparse-manifest", "patches": []}))
    final = describe(path)
    with pytest.raises(ValueError):
        shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=output)
    assert not list(output.iterdir())
