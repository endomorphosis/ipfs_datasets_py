"""Full report bytes survive publication without inference or authority."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/publish_legacy_logic_reports.py"
spec = importlib.util.spec_from_file_location("full_logic_report_publisher", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def receipt(tmp_path):
    text = "The agency shall retain records."
    document = {"views": {"deontic": {"logic_family": "deontic", "formula": "O(retain(records))"}}}
    inner = json.dumps(document, sort_keys=True, allow_nan=False).encode()
    row = {"source_span_id": "span1", "sample_id": "sample1", "text": text,
        "source_sha256": module._sha(text.encode()), "legal_id": "usc:5:1",
        "admitted": False, "formalized": False, "lake": {"admitted": False},
        "compiler": {"rules": [{"action": "retain"}], "admitted": False, "formalized": False},
        "raw_decoder": {"embedding": [0.1, 0.2]},
        "logic_target_observation": {"document": document, "document_bytes": len(inner),
                                      "document_sha256": module._sha(inner)}}
    body = {"schema_version": "legacy-span-cuda-diagnostic/v1", "admitted": False,
        "formalized": False, "training_executed": False, "requested_span_count": 1,
        "sample_count": 1, "rows": [row], "checkpoint": {"sha256": "a" * 64},
        "producer_source": {"sha256": "b" * 64}}
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(body, indent=3) + "\n")
    return source, body


class Hub:
    def __init__(self):
        self.head = "a" * 40
        self.files = {}
        self.commits = []
        self.corrupt = False
    def repo_info(self, **kwargs):
        return SimpleNamespace(sha=kwargs.get("revision", self.head))
    def get_paths_info(self, **kwargs):
        return [SimpleNamespace(path=name, size=len(self.files[name]),
                lfs={"sha256": "0" * 64 if self.corrupt else module._sha(self.files[name])})
                for name in kwargs["paths"] if name in self.files]
    def create_commit(self, **kwargs):
        assert kwargs["parent_commit"] == self.head
        for op in kwargs["operations"]:
            assert op.path_in_repo not in self.files
            self.files[op.path_in_repo] = op.path_or_fileobj
        self.commits.append(kwargs); self.head = "b" * 40
        return SimpleNamespace(oid=self.head)


def test_exact_bytes_gzip_deterministic_and_spaced_document_verified(tmp_path):
    source, body = receipt(tmp_path)
    prepared = module.prepare_report(source, tmp_path / "out")
    assert gzip.decompress(Path(prepared["report"]["path"]).read_bytes()) == source.read_bytes()
    assert module.prepare_report(source, tmp_path / "out") == prepared
    assert prepared["summary"]["counts"]["compiler_rule_count"] == 1
    assert prepared["summary"]["counts"]["source_bridge_document_count"] == 1
    check = prepared["summary"]["source_document_verification"][0]
    assert check["status"] == "verified" and check["matching_serialization_profile"] == "json_default_spaced"
    assert prepared["summary"]["actual_logic_families"] == ["deontic"]
    result = module.publish_report(prepared)
    assert result["uploaded"] is False and result["dry_run"] is True


def test_verified_cas_upload_is_idempotent(tmp_path):
    source, _ = receipt(tmp_path)
    prepared = module.prepare_report(source, tmp_path / "out")
    hub = Hub()
    result = module.publish_report(prepared, upload=True, api=hub)
    assert result["uploaded"] is True and result["commit_sha"] == "b" * 40
    assert len(hub.files) == 2 and len(hub.commits) == 1
    assert module.publish_report(prepared, upload=True, api=hub) == result
    assert len(hub.commits) == 1
    hub.corrupt = True
    with pytest.raises(ValueError, match="hash or size"):
        module.publish_report(prepared, upload=True, api=hub)


def test_remote_conflict_refuses_overwrite(tmp_path):
    source, _ = receipt(tmp_path)
    prepared = module.prepare_report(source, tmp_path / "out")
    hub = Hub(); hub.files[prepared["report"]["path_in_repo"]] = b"different"
    with pytest.raises(ValueError, match="hash or size"):
        module.publish_report(prepared, upload=True, api=hub)
    assert hub.commits == []


@pytest.mark.parametrize("change", ["source_hash", "sample_count", "admitted"])
def test_invalid_source_or_authority_rejected(tmp_path, change):
    source, body = receipt(tmp_path)
    if change == "source_hash": body["rows"][0]["source_sha256"] = "bad"
    elif change == "sample_count": body["sample_count"] = 2
    else: body["admitted"] = True
    source.write_text(json.dumps(body))
    with pytest.raises(ValueError): module.prepare_report(source, tmp_path / "out")


def test_inner_identity_mismatch_is_retained_as_historical_unverified_evidence(tmp_path):
    source, body = receipt(tmp_path)
    body["rows"][0]["logic_target_observation"]["document_sha256"] = "bad"
    source.write_text(json.dumps(body))
    result = module.prepare_report(source, tmp_path / "out")
    assert result["summary"]["source_document_verification"][0]["status"] == "recorded_identity_mismatch_or_absent"
    assert result["summary"]["training_qualification_granted"] is False


def test_symlink_and_changed_prepared_file_rejected(tmp_path):
    source, _ = receipt(tmp_path)
    link = tmp_path / "link.json"; link.symlink_to(source)
    with pytest.raises(ValueError, match="unaliased"): module.prepare_report(link, tmp_path / "out")
    prepared = module.prepare_report(source, tmp_path / "out")
    Path(prepared["report"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed before publication"):
        module.publish_report(prepared)
