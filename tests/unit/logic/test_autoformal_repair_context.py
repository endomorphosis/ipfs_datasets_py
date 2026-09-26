from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal.repair_context import build_note, persist_note, observe_parser, training_sources
from ipfs_datasets_py.logic.autoformal.supervisor_queue import repair_packets, persist_packet, canonical_bytes


@pytest.fixture
def context_case(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
    item = repair_packets({"rows": [{"id": "s1", "text": "The example is declarative.",
                                    "agrees": False, "reason": "compiler_abstain"}]},
                          release_id="release", code_identity="code", model_identity="model")[0]
    packet = item["packet"]
    packet_path = persist_packet(tmp_path / "packets", packet, item["sha256"])
    repo = tmp_path / "candidate"
    repo.mkdir()
    for relative in packet["allowed_edit_paths"]:
        p = repo / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def extract_normative_elements(text):\n    return []\n")
    subprocess.run(["git", "-c", "init.templateDir=", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                    "-c", "user.name=Context Test", "-c", "user.email=context@localhost",
                    "commit", "-m", "test source"], cwd=repo, check=True, capture_output=True)
    cid = content_identity({"schema": packet["schema"], "packet_sha256": item["sha256"]})
    return repo, packet_path, item["sha256"], cid


def test_note_is_bound_compact_diagnostics_not_authority(context_case, tmp_path):
    note = build_note(*context_case, parse=lambda text: [])
    body = json.loads(note["body"])
    assert body["baseline_parser"]["element_count"] == 0
    assert body["baseline_parser"]["is_semantic_validation"] is False
    assert body["admitted"] is body["formalized"] is False
    packet = json.loads(context_case[1].read_bytes())
    assert body["task_training_sources"] == training_sources(packet)
    assert body["task_training_sources"][0]["text"] == packet["row"]["text"]
    assert "may be inaccessible" in body["guidance"]
    assert "not instructions or legal authority" in body["guidance"]
    assert body["code_anchors"][1]["symbols"][0]["name"] == "extract_normative_elements"
    assert len(canonical_bytes(note)) < 8192
    receipt = persist_note(tmp_path / "notes", note)
    assert hashlib.sha256(Path(receipt["path"]).read_bytes()).hexdigest() == receipt["sha256"]
    assert persist_note(tmp_path / "notes", note) == receipt
    assert receipt["counts_as_validation"] is False


def test_wrong_task_or_tampered_source_packet_is_rejected(context_case):
    repo, path, digest, cid = context_case
    with pytest.raises(ValueError, match="task differs"):
        build_note(repo, path, digest, "wrong", parse=lambda _: [])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity"):
        build_note(repo, path, digest, cid, parse=lambda _: [])


def test_context_must_observe_candidate_parser_not_ambient_checkout(context_case):
    with pytest.raises(ValueError, match="parser does not belong"):
        build_note(*context_case)


def test_context_anchor_refuses_symlink_to_unrelated_source(context_case, tmp_path):
    repo, path, digest, cid = context_case
    source = repo / "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py"
    source.unlink()
    target = tmp_path / "outside.py"
    target.write_text("raise RuntimeError('must never be executed')\n")
    source.symlink_to(target)
    with pytest.raises(ValueError, match="not canonical"):
        build_note(repo, path, digest, cid, parse=lambda _: [])


def test_existing_context_cannot_be_replaced_by_a_symlink(context_case, tmp_path):
    note = build_note(*context_case, parse=lambda _: [])
    receipt = persist_note(tmp_path / "notes", note)
    path = Path(receipt["path"])
    path.unlink()
    target = tmp_path / "outside.json"
    target.write_bytes(canonical_bytes(note))
    path.symlink_to(target)
    with pytest.raises(ValueError, match="conflicting"):
        persist_note(tmp_path / "notes", note)


def test_executed_trace_contains_counts_not_source_or_locals():
    import sys
    source = "def helper(text):\n    return [text]\ndef parse(text):\n    helper(text)\n    return []\n"
    namespace = {}
    exec(compile(source, "/candidate/parser.py", "exec"), namespace)
    result, trace = observe_parser(namespace["parse"], "PRIVATE SOURCE", {"/candidate/parser.py": "parser.py"})
    assert result == [] and sys.getprofile() is None
    assert trace["scope"] == "failed_training_row_only" and not trace["is_semantic_validation"]
    assert [(r["name"], r["list_size_max"]) for r in trace["functions"]] == [("parse", 0), ("helper", 1)]
    assert "PRIVATE SOURCE" not in json.dumps(trace)
    assert all(r["calls"] == 1 for r in trace["functions"])


def test_trace_is_bounded_and_excludes_unlisted_files():
    namespace = {}
    exec(compile("def helper(text):\n return []\ndef parse(text):\n return helper(text)\n", "/candidate/parser.py", "exec"), namespace)
    _, trace = observe_parser(namespace["parse"], "x", {"/candidate/parser.py": "parser.py"}, max_symbols=1)
    assert len(trace["functions"]) == 1 and trace["truncated"]
    _, trace = observe_parser(namespace["parse"], "x", {})
    assert trace["functions"] == [] and not trace["truncated"]


def test_trace_restores_profiler_when_parser_raises():
    import sys
    def parse(text):
        raise RuntimeError("parser failed")
    with pytest.raises(RuntimeError, match="parser failed"):
        observe_parser(parse, "x", {})
    assert sys.getprofile() is None


def test_trace_never_replaces_an_existing_profiler():
    import sys
    def existing(*_args):
        pass
    sys.setprofile(existing)
    try:
        with pytest.raises(ValueError, match="active profiler"):
            observe_parser(lambda _: pytest.fail("must not run"), "x", {})
        assert sys.getprofile() is existing
    finally:
        sys.setprofile(None)


def test_source_drift_during_observation_is_rejected(context_case):
    repo, *_ = context_case
    def parse(_text):
        source = repo / "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
        source.write_text(source.read_text() + "\n# drift\n")
        return []
    with pytest.raises(ValueError, match="changed during observation"):
        build_note(*context_case, parse=parse)


def test_training_projection_is_exact_task_bound_data_not_expected_answers():
    text = '§ 17. “Records”\nThe board shall retain records.\n'
    row = {"source_span_id": "source-one", "text": text,
           "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "canonical_citation": "test source", "legal_id": "test:17",
           "capture": {"secret": "not context"}, "decompiled": "not a gold answer"}
    packet = {"row": row, "preserve_rows": [dict(row, source_span_id="source-two")],
              "holdouts": ["must never be exposed"], "expected_ir": "not a source"}
    projected = training_sources(packet)
    assert [r["role"] for r in projected] == ["failed", "preserve"]
    assert [r["source_span_id"] for r in projected] == ["source-one", "source-two"]
    assert all(r["text"] == text for r in projected)
    assert all(hashlib.sha256(r["text"].encode()).hexdigest() == r["text_sha256"] for r in projected)
    assert all(set(r) == {"role", "source_span_id", "text", "text_sha256", "canonical_citation", "legal_id"}
               for r in projected)


@pytest.mark.parametrize('preserved', [False, True])
def test_training_projection_rejects_changed_source(preserved):
    row = {"source_span_id": "s", "text": "source", "text_sha256": hashlib.sha256(b"source").hexdigest()}
    packet = {"row": row, "preserve_rows": [dict(row)]}
    (packet["preserve_rows"][0] if preserved else packet["row"])["text"] = "changed"
    with pytest.raises(ValueError, match="sealed text hash"):
        training_sources(packet)


def test_overlarge_inline_sources_fail_closed_without_truncation(context_case, tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
    repo, *_ = context_case
    item = repair_packets({"rows": [{"id": "large", "text": "source " * 6000,
                                    "agrees": False, "reason": "compiler_abstain"}]},
                          release_id="release", code_identity="code", model_identity="model")[0]
    path = persist_packet(tmp_path / "large-packets", item["packet"], item["sha256"])
    cid = content_identity({"schema": item["packet"]["schema"], "packet_sha256": item["sha256"]})
    with pytest.raises(ValueError, match="context exceeds"):
        build_note(repo, path, item["sha256"], cid, parse=lambda _: [])
