"""Authored span diagnostics isolate new values and keep targets out of inputs."""
import copy
import importlib.util
import json
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("legal_span_prepare", ROOT / "scripts/ops/legal_ir/prepare_legal_span_experiment.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def test_frozen_panels_hold_out_values_and_template_qualifier_compositions():
    panels = prepare.make_panels()
    assert {split: len(rows) for split, rows in panels.items()} == {"train": 288, "tuning": 48, "challenge": 192}
    evidence = prepare.check_panels(panels)
    assert evidence["challenge_template_qualifier_pair_overlap"] == 0
    assert evidence["canonical_value_novelty"]["challenge"]["action"] == {"distinct_values": 8, "unseen_in_train": 4}
    for field in ("actor", "object", "conditions", "exceptions", "temporal"):
        assert evidence["canonical_value_novelty"]["challenge"][field]["unseen_in_train"] == 8


def test_every_authored_facet_is_an_exact_unique_nonoverlapping_source_span():
    for rows in prepare.make_panels().values():
        for row in rows:
            spans = prepare.source_spans(row["source_text"], row["canonical_ir"])
            rule = row["canonical_ir"]["rules"][0]
            for key, value in spans.items():
                if key in prepare.FIELDS[:3]:
                    assert row["source_text"][value[0]:value[1]] == rule[key]
                else:
                    assert [row["source_text"][start:end] for start, end in value] == rule[key]


@pytest.mark.parametrize("mutation,expected", [("duplicate", "exactly once"), ("partial", "token aligned"), ("overlap", "overlap")])
def test_ambiguous_partial_or_overlapping_target_spans_are_rejected(mutation, expected):
    row = prepare.make_panels()["train"][0]
    text, ir = row["source_text"], copy.deepcopy(row["canonical_ir"])
    if mutation == "duplicate":
        text += " " + ir["rules"][0]["actor"]
    elif mutation == "partial":
        ir["rules"][0]["action"] = "nspect"
    else:
        ir["rules"][0]["conditions"] = ["County Records"]
    with pytest.raises(ValueError, match=expected):
        prepare.source_spans(text, ir)


def test_counterfactual_modalities_cannot_be_split_apart():
    panels = prepare.make_panels()
    panels["challenge"].append(panels["train"].pop())
    with pytest.raises(ValueError, match="incomplete|overlaps"):
        prepare.check_panels(panels)


def test_changed_visible_target_hash_is_detected():
    panels = prepare.make_panels()
    panels["train"][0]["canonical_target_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="target hash"):
        prepare.check_panels(panels)


def test_real_cache_observations_preserve_source_without_inventing_gold():
    queue = {"repository": "justicedao/uscode-autoformal-span-cache", "revision": prepare.REVISION,
             "entries": [{"source_span_id": "fragment", "source_text_variants": ["L."],
                          "source_text_consistent_across_occurrences": True, "legal_ids": ["usc:x"]}]}
    row = prepare.observed_panel(queue)[0]
    assert row["source_text"] == "L."
    assert not row["training_qualified"] and not row["target_available"]
    assert not {"canonical_ir", "source_spans", "formal_embedding"} & set(row)


def test_formal_serialization_excludes_source_and_is_stable():
    row = prepare.make_panels()["train"][0]
    text = prepare.formal_text(row["canonical_ir"])
    assert json.loads(text) == row["canonical_ir"]
    assert row["source_text"] not in text
    assert text == prepare.formal_text({"rules": [dict(reversed(list(row["canonical_ir"]["rules"][0].items())))]})


def test_frozen_artifact_is_exclusive_and_detects_tampering(tmp_path):
    path = tmp_path / "frozen.json"
    ref = prepare.save(path, {"fixed": True})
    with pytest.raises(FileExistsError):
        prepare.save(path, {"fixed": False})
    path.write_text('{"fixed":false}')
    with pytest.raises(ValueError, match="differs"):
        prepare.verify_ref(ref)


@pytest.fixture
def validation_case(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipts
    generated = prepare.make_panels()
    rows = {key: [copy.deepcopy(generated[key][0])] for key in ("train", "tuning", "challenge")}
    for key in ("canonical_ir", "source_spans"):
        rows["challenge"][0].pop(key)
    preparer_ref = prepare.save(tmp_path / "preparer.json", {"fixture": True})
    queue_ref = prepare.save(tmp_path / "queue.json", {})
    plan_rows = [{"id": row["id"], "split": split, **{key: row.get(key) for key in (
        "source_sha256", "canonical_target_sha256", "family_group", "template_id", "qualifier_pattern")}}
        for split, items in rows.items() for row in items]
    plan_ref = prepare.save(tmp_path / "plan.json", {"preparer": preparer_ref,
        "rows": plan_rows, "split_counts": {key: len(items) for key, items in rows.items()}})
    # Deliberately not JSON: validation must only hash this unopened target file.
    sealed_path = tmp_path / "sealed.json"
    sealed_path.write_text("sealed target bytes are never parsed")
    sealed_ref = prepare.file_ref(sealed_path)
    receipt_data, receipt_refs, bindings, paths = {}, [], [], {}
    for role in ("source", "formal"):
        data = {"model": {"fixture": True}, "model_assets": [], "inputs": [], "results": []}
        ref = prepare.save(tmp_path / f"{role}-native.json", {"fixture_role": role})
        receipt_refs.append({"role": role, **ref})
        receipt_data[ref["path"]] = data
        for split, items in rows.items():
            if role == "formal" and split != "train":
                continue
            for row in items:
                text = row["source_text"] if role == "source" else prepare.formal_text(row["canonical_ir"])
                digest = prepare.sha(text.encode())
                source_path = tmp_path / (digest + ".txt")
                source_path.write_text(text)
                paths[digest] = str(source_path)
                input_id = row["id"] + "-" + role
                data["inputs"].append({"input_id": input_id, "text": text,
                                       "source": {"artifact": {"sha256": digest, "bytes": len(text.encode())}}})
                bits = struct.pack(">384f", *([0.125] * 384)).hex()
                data["results"].append({"input_id": input_id, "status": "embedded", "vector": {"bits": bits}})
                vector_key = "embedding" if role == "source" else "formal_embedding"
                row[vector_key], row[vector_key + "_status"] = [0.125] * 384, "embedded"
                bindings.append({"id": row["id"], "split": split, "role": role, "input_id": input_id,
                                 "receipt_sha256": ref["sha256"], "text_sha256": digest})
    def fake_loader(path, *, resolver, **kwargs):
        data = receipt_data[str(path)]
        for item in data["inputs"]:
            resolver(item["source"]["artifact"])
        return type("NativeReceiptFixture", (), {"to_dict": lambda self: data})()
    monkeypatch.setattr(receipts, "load_embedding_production_receipt", fake_loader)
    corpus = {"schema": "legal-span-experiment-corpus/v1", "splits": rows, "frozen_plan": plan_ref,
              "preparer": preparer_ref, "dataset": {"review_queue": queue_ref}, "sealed_targets": sealed_ref,
              "source_paths": paths, "embedding_receipts": receipt_refs,
              "embedding_bindings": prepare.save(tmp_path / "bindings.json", bindings),
              "model": {"fixture": True}, "model_assets": []}
    return corpus, sealed_path, receipt_data


def test_validation_hashes_sealed_file_without_parsing_targets(validation_case):
    corpus, sealed_path, _ = validation_case
    evidence = prepare.validate_inputs(corpus, sealed_path)
    assert not evidence["sealed_target_json_parsed"]
    assert evidence["formal_targets_train_only"] and evidence["native_vectors_verified"]


@pytest.mark.parametrize("field,value", [("canonical_ir", {}), ("source_spans", {}),
                                         ("formal_embedding", [0.0] * 384)])
def test_validation_rejects_target_access_in_challenge_inputs(validation_case, field, value):
    corpus, sealed_path, _ = validation_case
    corpus["splits"]["challenge"][0][field] = value
    with pytest.raises(ValueError, match="target access"):
        prepare.validate_inputs(corpus, sealed_path)


def test_validation_rejects_tampered_vector(validation_case):
    corpus, sealed_path, _ = validation_case
    corpus["splits"]["train"][0]["formal_embedding"][0] = 0.5
    with pytest.raises(ValueError, match="vector differs"):
        prepare.validate_inputs(corpus, sealed_path)


def test_validation_checks_native_input_text_not_just_vector_bits(validation_case):
    corpus, sealed_path, data = validation_case
    source_ref = next(ref for ref in corpus["embedding_receipts"] if ref["role"] == "source")
    data[source_ref["path"]]["inputs"][0]["text"] = "A different source."
    with pytest.raises(ValueError, match="different input text"):
        prepare.validate_inputs(corpus, sealed_path)
