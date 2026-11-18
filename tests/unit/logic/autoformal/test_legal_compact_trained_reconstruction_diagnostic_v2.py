"""Two proposed retained-state diagnostics; no new fitting or statutory credit.

Source-only candidate until installed, frozen and run under normal admission.
The first prefix contains transport syntax only. Both original BOS predictions
finish before reference access for training-exposed engineering comparisons.
Recorded interop=20 is checked, never changed to manufacture compatibility.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat

import pytest
import torch
from torch.nn import functional as functional

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_trained_runtime_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens


PACKET_PATH = Path("/home/barberb/lift_coding/artifacts/legal-ir-trained-inference-retained-handoff-20261017-01/inference-inputs.json")
PACKET_SHA = "b44d6d56a99569a78f74c702fac5d9c550a3506d31e39255aa038528816b3894"
CHECKPOINT_SHA = "a98a6244222b6379cd4669905b0d14b87e30761fe9cbc795206b16151ba69c7b"
REFERENCE_LEDGER_SHA = "17feef30e6d19095828a419e94dd8173003923bd42119ec136507839fa363c2e"
MAX_PUBLIC_FORWARDS = 129
EQUATION_SOURCES = [
    {"path": "/home/barberb/.local/lib/python3.12/site-packages/torch/nn/modules/rnn.py",
     "bytes": 76132, "sha256": "902deeba8fd7d3c92b00e3557071b3bb41cf747bd4b2b9d63757d88562688bde"},
    {"path": "/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "bytes": 35427, "sha256": "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"},
]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def parse(raw):
    def pairs(rows):
        result = {}
        for key, child in rows:
            assert key not in result, "duplicate saved JSON key"
            result[key] = child
        return result
    def nonfinite(_):
        raise ValueError("nonfinite saved JSON refused")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)


def raw_file(path, *, expected=None, size=None):
    assert path.is_absolute() and path.resolve(strict=True) == path
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4 * 1024**2
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    witness = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    assert witness(before) == witness(after) == witness(path.lstat()) and len(raw) == before.st_size
    if expected is not None: assert sha(raw) == expected
    if size is not None: assert len(raw) == size
    return raw


def no_authority(value):
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is int and value["training_mask"] == 0
    assert type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0


@pytest.fixture(scope="module", autouse=True)
def no_optimizer_or_training():
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append("forbidden optimizer/trainer entry")
        pytest.fail("retained diagnostic attempted optimizer allocation, restore or training")
    # The real runtime below also checks its complete recorded platform/build.
    assert str(torch.__version__) == "2.13.0+cu130"
    assert torch.get_num_threads() == 1 and torch.get_num_interop_threads() == 20
    assert str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32
    assert not torch.cuda.is_initialized() and not torch.is_autocast_enabled("cpu")
    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(torch.optim.Optimizer, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "__init__", forbidden)
        patch.setattr(torch.optim.Adam, "step", forbidden)
        patch.setattr(trainer, "_restore", forbidden)
        for name in ("build_compact_content_training_v2", "train_compact_content_v2",
                     "validate_compact_content_training_v2", "compact_content_training_bytes_v2",
                     "load_compact_content_training_v2"):
            patch.setattr(trainer, name, forbidden)
        yield attempts
    assert attempts == [] and torch.equal(rng, torch.get_rng_state())
    assert torch.get_num_threads() == 1 and torch.get_num_interop_threads() == 20


@pytest.fixture(scope="module")
def material(no_optimizer_or_training):
    spelling = os.environ.get("LEGAL_COMPACT_TRAINED_RECONSTRUCTION_PACKET")
    assert spelling == str(PACKET_PATH), "one exact retained packet required; no discovery or fallback"
    packet_raw = raw_file(PACKET_PATH, expected=PACKET_SHA, size=8302)
    packet = parse(packet_raw)
    assert packet["schema"] == "legal-compact-retained-inference-inputs/v1"
    assert packet["not_a_holdout"] is True and packet["new_optimizer_steps_permitted"] == 0
    assert packet["encoder_sha256"] is None and packet["source_encoder_authenticated"] is False
    assert packet["context_permission_verified"] is False
    assert packet["training_mask"] == packet["evaluation_gold_mask"] == 0
    reference = packet["checkpoint"]["artifact"]
    checkpoint_raw = raw_file(Path(reference["path"]), expected=reference["sha256"], size=reference["bytes"])
    checkpoint = parse(checkpoint_raw)
    assert sha(checkpoint_raw) == digest(checkpoint) == packet["checkpoint"]["canonical_sha256"] == CHECKPOINT_SHA
    assert checkpoint["progress"] == {"optimizer_steps": 2, "epochs_completed": 1, "row_cursor": 0}
    assert checkpoint["runtime"] == packet["checkpoint"]["runtime"]
    assert checkpoint["runtime"]["num_threads"] == 1 and checkpoint["runtime"]["num_interop_threads"] == 20
    assert checkpoint["initial_checkpoint_sha256"] == packet["checkpoint"]["initial_checkpoint_sha256"]
    assert checkpoint["parent_checkpoint_sha256"] == packet["checkpoint"]["parent_checkpoint_sha256"]
    assert checkpoint["weights_sha256"] == digest(checkpoint["model_state"])
    assert len(checkpoint["codec"]["vocabulary"]) == 537 and checkpoint["max_total_ids"] == 512
    population_ref = packet["population"]
    population_raw = raw_file(Path(population_ref["path"]), expected=population_ref["sha256"], size=population_ref["bytes"])
    population = parse(population_raw)
    training = parse(checkpoint["population_raw_utf8"].encode("utf-8"))
    assert sha(checkpoint["population_raw_utf8"].encode()) == checkpoint["population_sha256"]
    assert len(packet["rows"]) == len(population["rows"]) == len(training["rows"]) == 2
    data_pins = [{"path": str(PACKET_PATH), "bytes": len(packet_raw), "sha256": PACKET_SHA},
                 reference, population_ref]
    for index, (row, declared, selected) in enumerate(zip(packet["rows"], training["rows"], population["rows"])):
        assert row["id"] == declared["id"] == selected["id"]
        assert row["source_group"] == declared["source_group"]
        assert len(row["conditioning"]) == 384 and digest(row["conditioning"]) == row["conditioning_sha256"] == declared["conditioning_sha256"]
        assert sha(row["source_utf8"].encode()) == row["source_sha256"] == declared["source_sha256"] == selected["source_sha256"]
        assert sha(row["context_utf8"].encode()) == row["context_sha256"] == declared["context_sha256"]
        base = PACKET_PATH.parent / "inputs"
        for suffix, raw in (("source.txt", row["source_utf8"].encode()),
                            ("model-context.json", row["context_utf8"].encode())):
            path = base / ("row-" + str(index) + "-" + suffix)
            assert raw_file(path, expected=sha(raw), size=len(raw)) == raw
            data_pins.append({"path": str(path), "bytes": len(raw), "sha256": sha(raw)})
        wrapper_path = base / ("row-" + str(index) + "-source-context.json")
        wrapper_raw = raw_file(wrapper_path, expected=row["source_context_sha256"])
        wrapper = parse(wrapper_raw)
        assert wrapper["source_sha256"] == row["source_sha256"]
        assert wrapper["origin"] == "authored_engineering_fixture_unverified"
        assert row["source_context_sha256"] == selected["context_sha256"] != row["context_sha256"]
        data_pins.append({"path": str(wrapper_path), "bytes": len(wrapper_raw), "sha256": sha(wrapper_raw)})
        for suffix, key in (("catalog.json", "catalog_sha256"), ("nomination-report.json", "nomination_report_sha256")):
            path = base / ("row-" + str(index) + "-" + suffix)
            raw = raw_file(path, expected=wrapper[key])
            data_pins.append({"path": str(path), "bytes": len(raw), "sha256": sha(raw)})
    for reference in EQUATION_SOURCES:
        raw_file(Path(reference["path"]), expected=reference["sha256"], size=reference["bytes"])
    return {"packet": packet, "packet_raw": packet_raw, "checkpoint": checkpoint,
            "checkpoint_raw": checkpoint_raw, "population": population, "data_pins": data_pins}


def manual_gru_scores(checkpoint, vector, ids):
    """Pinned PyTorch GRU equations; no GRU object or product model helper.

    rnn.py1215-1218/1308-1321 supplies gate order and reset-after-linear form.
    modal_latent_formula.py152-190 supplies projection/conditioning/output.
    """
    weights = {name: torch.tensor(value, dtype=torch.float32, device="cpu")
               for name, value in checkpoint["model_state"].items()}
    def linear(value, stem):
        return functional.linear(value, weights[stem + ".weight"], weights[stem + ".bias"])
    with torch.inference_mode():
        value = torch.tensor(vector, dtype=torch.float32, device="cpu")
        hidden = torch.tanh(linear(value + linear(torch.tanh(linear(value, "projection_down")), "projection_up"), "condition"))
        result = []
        for token in ids:
            input_gates = functional.linear(weights["target_embedding.weight"][token],
                weights["decoder.weight_ih_l0"], weights["decoder.bias_ih_l0"])
            hidden_gates = functional.linear(hidden, weights["decoder.weight_hh_l0"], weights["decoder.bias_hh_l0"])
            ir, iz, inn = input_gates.chunk(3)
            hr, hz, hn = hidden_gates.chunk(3)
            reset, update = torch.sigmoid(ir + hr), torch.sigmoid(iz + hz)
            hidden = (1 - update) * torch.tanh(inn + reset * hn) + update * hidden
            result.append(linear(hidden, "output"))
        return torch.stack(result)


def retain(directory, bodies, summary):
    artifacts = {}
    for name, raw in bodies.items():
        assert Path(name).name == name
        path = directory / name
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        assert raw_file(path, expected=sha(raw), size=len(raw)) == raw
        artifacts[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    assert len(artifacts) == 8 and sum(row["bytes"] for row in artifacts.values()) < 24 * 1024**2
    value = {"schema": "legal-compact-trained-reconstruction-diagnostic-fixture/v2",
             "checkpoint_sha256": CHECKPOINT_SHA, "packet_sha256": PACKET_SHA,
             "summary": summary, "artifacts": artifacts}
    raw, path = wire(value), directory / "reconstruction-diagnostic-manifest.json"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


@pytest.fixture(scope="module")
def diagnostic(material, no_optimizer_or_training, tmp_path_factory):
    case, packet = material, material["packet"]
    checkpoint = case["checkpoint"]
    original = wire({"checkpoint": checkpoint, "packet": packet})
    directory = tmp_path_factory.mktemp("compact-trained-reconstruction-diagnostic-v2", numbered=False)
    events, active = [], {"phase": None, "prefix": None, "reference_access": False}
    real_forward, real_gru = subject._forward, torch.nn.GRU.forward
    public_count = gru_count = 0
    def observed_gru(model, inputs, *args, **kwargs):
        nonlocal gru_count
        assert active["phase"] is not None and gru_count < MAX_PUBLIC_FORWARDS
        assert active["reference_access"] is False, "no GRU dispatch after metric reference access"
        result = real_gru(model, inputs, *args, **kwargs)
        gru_count += 1
        events.append({"event": "gru_forward", "phase": active["phase"],
            "prefix_ids": list(active["prefix"]), "input_shape": list(inputs.shape),
            "output_shape": list(result[0].shape), "gru_output_sha256": digest(result[0].detach().tolist())})
        return result
    def observed_forward(value, conditioning, prefix_ids):
        nonlocal public_count
        assert public_count < MAX_PUBLIC_FORWARDS and active["phase"] is not None
        assert active["reference_access"] is False, "no model dispatch after metric reference access"
        assert digest(value) == CHECKPOINT_SHA and value["weights_sha256"] == checkpoint["weights_sha256"]
        active["prefix"] = list(prefix_ids)
        result = real_forward(value, conditioning, prefix_ids)
        public_count += 1
        events.append({"event": "public_forward", "phase": active["phase"], "prefix_ids": list(prefix_ids),
            "checkpoint_sha256": CHECKPOINT_SHA, "weights_sha256": value["weights_sha256"],
            "conditioning_sha256": digest(conditioning), "logits_sha256": digest(result["logits"]),
            "output_shape": result["output_shape"]})
        return result
    codec = checkpoint["codec"]
    positions = {piece: index for index, piece in enumerate(codec["vocabulary"])}
    lexical = ["{", '"schema"', ":", '"legal-relational-compact-content/v1"', ",", '"tree"', ":", "["]
    prefix = [codec["bos_id"], *(positions[piece] for piece in lexical)]
    assert len(prefix) == 9
    row = packet["rows"][0]
    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(subject, "_forward", observed_forward)
        patch.setattr(torch.nn.GRU, "forward", observed_gru)
        active["phase"] = "authored_constructor_branch_score"
        score = subject.score_compact_content_trained_v2(checkpoint, row["conditioning"], prefix,
            row["context_utf8"].encode(), expected_checkpoint_sha256=CHECKPOINT_SHA,
            expected_context_sha256=row["context_sha256"])
        preceding = (public_count, gru_count)
        expected = manual_gru_scores(checkpoint, row["conditioning"], prefix)
        assert preceding == (public_count, gru_count) == (1, 1)
        actual = torch.tensor(score["logits"], dtype=torch.float32)
        torch.testing.assert_close(actual, expected[-1], rtol=2e-5, atol=2e-6)
        allowed = score["prefix_report"]["allowed_token_ids"]
        assert len(allowed) > 1
        label = positions['"forall"']  # One predeclared syntax probe, not a reference target.
        assert label in allowed
        ce = functional.cross_entropy(actual.unsqueeze(0), torch.tensor([label], dtype=torch.int64))
        equation_ce = torch.logsumexp(expected[-1].double(), dim=0) - expected[-1, label].double()
        assert math.isclose(float(ce), float(equation_ce), rel_tol=2e-5, abs_tol=2e-6)
        raw_best = max(range(537), key=lambda token: (score["logits"][token], -token))
        allowed_best = max(allowed, key=lambda token: (score["logits"][token], -token))
        assert score["selection"]["raw_argmax_token_id"] == raw_best
        assert score["selection"]["selected_token_id"] == allowed_best
        assert score["next_prefix_ids"] == prefix + [allowed_best]
        reference = {"schema": "legal-compact-retained-manual-gate-reference/v1", "prefix_ids": prefix,
            "prefix_origin": "authored_transport_syntax", "target_access": False,
            "equation_logits": expected[-1].tolist(), "equation_reference_count": 1,
            "GRU_object_constructed": False, "rtol": 2e-5, "atol": 2e-6,
            "maximum_absolute_error": float((actual - expected[-1]).abs().max()),
            "syntax_label_id": label, "public_logits_cross_entropy": float(ce),
            "independent_logsumexp_cross_entropy": float(equation_ce),
            "raw_argmax_token_id": raw_best, "allowed_argmax_token_id": allowed_best,
            "branch_allowed_token_count": len(allowed), "equation_sources": EQUATION_SOURCES,
            "numerical_CE_is_not_legal_accuracy_or_optimizer_loss": True}
        generations, results = [], []
        # Neither target nor reference ledger is opened before or during either original generation.
        for index, row in enumerate(packet["rows"]):
            active["phase"] = "bos_row_" + str(index)
            report = subject.generate_compact_content_trained_v2(checkpoint, row["conditioning"], [1],
                row["context_utf8"].encode(), expected_checkpoint_sha256=CHECKPOINT_SHA,
                expected_context_sha256=row["context_sha256"], max_new_tokens=64,
                prefix_origin="bos_seed", context_origin="authored_fixture")
            assert report["status"] in {"complete", "blocked", "step_budget_exhausted"}
            assert report["initial_prefix_ids"] == [1] and report["generated_ids"] == [1, *report["selected_token_ids"]]
            assert report["numerical_forward_count"] == report["emitted_token_count"] <= 64
            assert report["exposure"]["teacher_forcing"] is report["exposure"]["target_access"] is False
            assert report["optimizer_constructed"] is report["optimizer_state_restored"] is False
            assert report["training_executed"] is report["compact_optimizer_executed"] is False
            assert codec["pad_id"] not in report["generated_ids"]
            completed = report["status"] == "complete"
            assert (report["final_decoding"]["status"] == "valid_candidate") == completed
            assert (report["generated_ids"][-1] == codec["eos_id"]) == completed
            assert report["compact_training_steps"] == 2 and report["checkpoint_sha256"] == CHECKPOINT_SHA
            for step in report["trace"]:
                assert step["optimizer_constructed"] is step["optimizer_state_restored"] is step["optimizer_executed"] is False
                if step["numerical_forward_executed"]:
                    assert len(step["logits"]) == 537 and all(math.isfinite(value) for value in step["logits"])
                    assert step["logits_sha256"] == digest(step["logits"])
                    assert step["selection"]["selected_token_id"] in step["prefix_report"]["allowed_token_ids"]
                no_authority(step)
            no_authority(report)
            generations.append(report)
            results.append({"index": index, "id": row["id"], "source_group": row["source_group"],
                "source_sha256": row["source_sha256"], "conditioning_sha256": row["conditioning_sha256"],
                "model_context_sha256": row["context_sha256"], "source_context_sha256": row["source_context_sha256"],
                "status": report["status"], "reason": report["reason"],
                "final_decode_status": report["final_decoding"]["status"], "complete": completed,
                "EOS_emitted": completed, "numerical_forward_count": report["numerical_forward_count"],
                "emitted_token_count": report["emitted_token_count"],
                "branch_decision_count": sum(len(step["prefix_report"]["allowed_token_ids"]) > 1
                    for step in report["trace"] if step["numerical_forward_executed"]),
                "training_mask": 0, "evaluation_gold_mask": 0})
        # Freeze numerical dispatch before reading separately pinned reference bodies.
        # Encoding the references uses genuine public token/content owners and no model.
        counts_before_references = (public_count, gru_count)
        active["reference_access"] = True
        events.append({"event": "metric_reference_access", "metric_reference_access": True,
            "reference_access_after_all_model_calls": True,
            "public_model_forward_count": public_count, "gru_forward_count": gru_count,
            "both_original_generations_finished": True})
        ledger_path = PACKET_PATH.parent / "engineering-reference-ledger.json"
        ledger_raw = raw_file(ledger_path, expected=REFERENCE_LEDGER_SHA, size=980)
        ledger = parse(ledger_raw)
        assert ledger["schema"] == "legal-retained-engineering-reference-ledger/v1"
        assert ledger["prediction_receives_reference_bodies"] is False
        assert ledger["heldout_or_legal_accuracy_eligible"] is False and len(ledger["rows"]) == 2
        reference_rows = []
        training = parse(checkpoint["population_raw_utf8"].encode())
        for row, declared, entry, report, result in zip(packet["rows"], training["rows"], ledger["rows"], generations, results):
            assert row["id"] == entry["id"] == declared["id"] == result["id"]
            assert entry["training_exposed"] is True and entry["evaluation_gold_mask"] == 0
            target = entry["target"]
            assert target["sha256"] == declared["target_sha256"]
            target_raw = raw_file(Path(target["path"]), expected=target["sha256"], size=target["bytes"])
            encoded = tokens.encode_compact_content_tokens_v1(target_raw, row["context_utf8"].encode(),
                expected_content_sha256=target["sha256"], expected_context_sha256=row["context_sha256"],
                codec=codec, expected_codec_sha256=checkpoint["codec_sha256"])
            assert encoded["original_content_raw_sha256"] == target["sha256"]
            assert encoded["context_raw_sha256"] == row["context_sha256"]
            no_authority(encoded)
            complete = report["status"] == "complete"
            exact_ids = complete and report["generated_ids"] == encoded["target_ids"]
            same_content = complete and report["final_decoding"]["prediction"]["content"] == encoded["prediction"]["content"]
            result.update(exact_target_id_match=exact_ids, structural_content_match=same_content)
            reference_rows.append({"id": row["id"], "target": target, "target_utf8": target_raw.decode(),
                "reference_encoding": encoded, "training_exposed": True,
                "exact_target_id_match": exact_ids, "structural_content_match": same_content,
                "evaluation_gold_mask": 0})
        assert counts_before_references == (public_count, gru_count)
        comparisons = {"schema": "legal-compact-post-generation-engineering-comparison/v1",
            "ledger": {"path": str(ledger_path), "bytes": len(ledger_raw), "sha256": REFERENCE_LEDGER_SHA},
            "metric_reference_access": True, "reference_access_after_all_model_calls": True,
            "model_counts_before_reference_access": {"public": counts_before_references[0], "GRU": counts_before_references[1]},
            "model_counts_after_reference_access": {"public": public_count, "GRU": gru_count},
            "model_calls_after_reference_access": 0, "reference_rows": reference_rows,
            "training_exposed_engineering_only": True, "legal_or_heldout_accuracy_eligible": False}
    assert wire({"checkpoint": checkpoint, "packet": packet}) == original
    assert torch.equal(rng, torch.get_rng_state()) and no_optimizer_or_training == []
    assert public_count == gru_count == 1 + sum(value["numerical_forward_count"] for value in generations) <= 129
    assert len(events) == 2 * public_count + 1 and events[-1]["event"] == "metric_reference_access"
    raw_file(ledger_path, expected=REFERENCE_LEDGER_SHA, size=980)
    for row in reference_rows:
        value = row["target"]
        raw_file(Path(value["path"]), expected=value["sha256"], size=value["bytes"])
    for value in [*case["data_pins"], *EQUATION_SOURCES]:
        raw_file(Path(value["path"]), expected=value["sha256"], size=value["bytes"])
    summary = {"public_model_forward_count": public_count, "gru_forward_count": gru_count,
        "manual_equation_evaluations": 1, "max_public_model_forward_count": 129,
        "optimizer_allocations": 0, "optimizer_updates": 0, "retained_checkpoint_optimizer_steps": 2,
        "population_count": 2, "predicted_rows": 2,
        "complete_count": sum(row["status"] == "complete" for row in results),
        "blocked_count": sum(row["status"] == "blocked" for row in results),
        "step_budget_exhausted_count": sum(row["status"] == "step_budget_exhausted" for row in results),
        "exact_target_id_match_count": sum(row["exact_target_id_match"] for row in results),
        "structural_content_match_count": sum(row["structural_content_match"] for row in results),
        "metric_reference_access": True, "reference_access_after_all_model_calls": True,
        "model_calls_after_reference_access": 0}
    scope = {"schema": "legal-compact-trained-reconstruction-diagnostic-scope/v2", "summary": summary,
        "results_by_row": results, "checkpoint_sha256": CHECKPOINT_SHA, "packet_sha256": PACKET_SHA,
        "manual_equation_reference_is_not_an_actual_GRU_forward": True,
        "numeric_event_counters_overlap": True, "targets_read": True, "reference_bodies_read": True,
        "targets_accessed_by_original_generations": False, "metric_reference_access": True,
        "reference_access_after_all_model_calls": True, "model_calls_after_reference_access": 0,
        "engineering_reference_comparison": comparisons,
        "heldout_evaluated": False, "statutory_meaning_verified": False,
        "source_encoder_authenticated": False, "context_permission_verified": False,
        "comparison_credit": 0, "training_mask": 0, "evaluation_gold_mask": 0}
    bodies = {"inference-inputs.json": case["packet_raw"], "retained-checkpoint.json": case["checkpoint_raw"],
        "branch-score.json": wire(score), "manual-reference.json": wire(reference),
        "generation-row-0.json": wire(generations[0]), "generation-row-1.json": wire(generations[1]),
        "observed-calls.json": wire(events), "scope.json": wire(scope)}
    manifest = retain(directory, bodies, summary)
    return {"manifest": manifest, "score": score, "manual": reference, "generations": generations,
            "scope": scope, "events": events}


def test_reconstruction_constructor_branch_matches_manual_gate_equations_without_training(diagnostic, record_property):
    record_property("compact_trained_reconstruction_diagnostic_fixture", json.dumps(diagnostic["manifest"], sort_keys=True))
    score, reference = diagnostic["score"], diagnostic["manual"]
    assert score["status"] == "scored" and score["output_shape"] == [1, 9, 537]
    assert len(score["prefix_report"]["allowed_token_ids"]) == reference["branch_allowed_token_count"] > 1
    assert reference["equation_reference_count"] == 1 and reference["GRU_object_constructed"] is False
    assert math.isfinite(reference["public_logits_cross_entropy"])
    assert math.isfinite(reference["independent_logsumexp_cross_entropy"])
    assert score["compact_training_steps"] == 2 and score["checkpoint_sha256"] == CHECKPOINT_SHA
    assert score["optimizer_constructed"] is score["optimizer_state_restored"] is score["optimizer_executed"] is False
    no_authority(score)


def test_reconstruction_both_bos_trials_retain_complete_blocked_or_exhausted_results(diagnostic):
    summary, rows = diagnostic["scope"]["summary"], diagnostic["scope"]["results_by_row"]
    assert summary["population_count"] == summary["predicted_rows"] == len(rows) == 2
    assert [row["id"] for row in rows] == ["fictional-retention", "fictional-inspection"]
    assert summary["complete_count"] + summary["blocked_count"] + summary["step_budget_exhausted_count"] == 2
    assert summary["public_model_forward_count"] == summary["gru_forward_count"] <= 129
    assert summary["manual_equation_evaluations"] == 1
    assert summary["optimizer_allocations"] == summary["optimizer_updates"] == 0
    assert diagnostic["scope"]["comparison_credit"] == 0
    assert diagnostic["scope"]["targets_read"] is diagnostic["scope"]["reference_bodies_read"] is True
    assert diagnostic["scope"]["targets_accessed_by_original_generations"] is False
    assert summary["metric_reference_access"] is summary["reference_access_after_all_model_calls"] is True
    assert summary["model_calls_after_reference_access"] == 0
    assert 0 <= summary["exact_target_id_match_count"] <= summary["complete_count"]
    assert 0 <= summary["structural_content_match_count"] <= summary["complete_count"]
    for row, report in zip(rows, diagnostic["generations"]):
        assert row["status"] == report["status"] and row["final_decode_status"] == report["final_decoding"]["status"]
        assert report["settings"]["max_new_tokens"] == 64
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
        no_authority(report)
