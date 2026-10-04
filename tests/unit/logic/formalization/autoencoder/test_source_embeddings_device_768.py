"""768D session controls with patched admission and real tiny CPU tensors.

The asset bytes and backend are authored protocol fixtures. These tests execute
small CPU tensor forwards, but never load the published GTE weights, fit a model,
download assets or qualify CUDA or multilingual source semantics.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
import torch


subject = importlib.import_module(
    "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_device_768"
)
reference = importlib.import_module(
    "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_768"
)
complete = importlib.import_module(
    "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_768_complete"
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class TinyTokenizer:
    """Deterministic authored tokenizer; no downloaded tokenizer is exercised."""
    padding_side = "right"

    def __init__(self):
        self.lengths = {}
        self.calls = []
        self.pad_defect = None
        self.encode_hook = None
        self.bad_tokens = None
        self.backend_tokenizer = SimpleNamespace(to_str=lambda: '{"authored_tokenizer":true}')
        self.special_tokens_map = {"bos_token": "<bos>", "eos_token": "<eos>"}
        self.truncation_side = "right"
        self.model_max_length = 8192
        self.pad_token_id = 0

    def encode(self, text, *, add_special_tokens, truncation):
        assert add_special_tokens is True and truncation is False
        self.calls.append(text)
        if self.encode_hook is not None:
            self.encode_hook()
        if self.bad_tokens is not None:
            return deepcopy(self.bad_tokens)
        width = self.lengths.get(text, len(text) + 2)
        return [1] + [2] * (width - 2) + [3]

    def pad(self, rows, *, padding, return_tensors):
        assert padding is True and return_tensors == "pt"
        width = max(len(row["input_ids"]) for row in rows)
        result = {key: torch.tensor(
            [row[key] + [0] * (width - len(row[key])) for row in rows],
            dtype=torch.int64,
        ) for key in ("input_ids", "attention_mask")}
        if self.pad_defect == "changed_token":
            result["input_ids"][0, 0] = 4
        elif self.pad_defect == "changed_mask":
            result["attention_mask"][0, 0] = 0
        elif self.pad_defect == "left_padding":
            result = {key: value.flip(1) for key, value in result.items()}
        elif self.pad_defect == "extra_field":
            result["token_type_ids"] = torch.zeros_like(result["input_ids"])
        elif self.pad_defect == "missing_mask":
            del result["attention_mask"]
        elif self.pad_defect == "float_tokens":
            result["input_ids"] = result["input_ids"].float()
        elif self.pad_defect == "non_tensor":
            result["input_ids"] = result["input_ids"].tolist()
        return result


class TinyEncoder(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = torch.nn.Embedding(32, 768, device="cpu", dtype=torch.float32)
        self.register_buffer("offset", torch.zeros(768), persistent=False)
        with torch.no_grad():
            self.embedding.weight.zero_()
            self.embedding.weight[:, 0] = 3
            self.embedding.weight[:, 1] = 4

    def forward(self, input_ids, attention_mask):
        return SimpleNamespace(last_hidden_state=self.embedding(input_ids) + self.offset)


class TinyCompleteModel(torch.nn.Module):
    """Real CPU embedding lookup and classifier; no training is performed."""
    def __init__(self):
        super().__init__()
        self.new = TinyEncoder()
        self.classifier = torch.nn.Linear(768, 1, device="cpu", dtype=torch.float32)
        with torch.no_grad():
            self.classifier.weight.zero_()
            self.classifier.bias.zero_()
        self.config = SimpleNamespace(vocab_size=32, hidden_size=768,
                                      max_position_embeddings=8192,
                                      to_dict=lambda: {"vocab_size": 32, "hidden_size": 768,
                                                       "max_position_embeddings": 8192})
        self.calls = []
        # Deliberate backend faults live outside primitive model configuration.
        # The guarded forward method itself remains unchanged after admission.
        self.controls = {"defect": None, "forward_hook": None}

    @property
    def defect(self):
        return self.controls["defect"]

    @defect.setter
    def defect(self, value):
        self.controls["defect"] = value

    @property
    def forward_hook(self):
        return self.controls["forward_hook"]

    @forward_hook.setter
    def forward_hook(self, value):
        self.controls["forward_hook"] = value

    def forward(self, **inputs):
        self.calls.append({name: value.detach().clone() for name, value in inputs.items()})
        if self.forward_hook is not None:
            self.forward_hook()
        if self.defect == "input_substitution":
            inputs["input_ids"][0, 0] = 4
        hidden = self.new(**inputs).last_hidden_state
        logits = self.classifier(hidden)
        if self.defect == "zero":
            hidden = torch.zeros_like(hidden)
        elif self.defect == "nan":
            hidden = hidden.clone(); hidden[0, 0, 0] = float("nan")
        elif self.defect == "inf":
            hidden = hidden.clone(); hidden[0, 0, 0] = float("inf")
        elif self.defect == "width":
            hidden = hidden[:, :, :384]
        elif self.defect == "dtype":
            hidden = hidden.double()
        elif self.defect == "batch":
            hidden = hidden[:0]
        elif self.defect == "sequence":
            hidden = hidden[:, :0]
        elif self.defect == "missing":
            return SimpleNamespace(logits=logits)
        return SimpleNamespace(last_hidden_state=hidden, logits=logits)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """Patch only asset admission and loading; exercise real session custody."""
    model_directory, code_directory = tmp_path / "model", tmp_path / "code"
    model_directory.mkdir(); code_directory.mkdir()
    payloads = {
        ("model", "config.json"): b'{"hidden_size":768,"max_position_embeddings":8192}',
        ("model", "tokenizer_config.json"): b'{"padding_side":"right"}',
        ("model", "special_tokens_map.json"): b'{"authored":true}',
        ("model", "tokenizer.json"): b'{"authored_protocol_tokenizer":true}',
        ("model", "model.safetensors"): b"protocol-only ordinary bytes, never tensor-loaded",
        ("code", "configuration.py"): b"# authored protocol fixture\n",
        ("code", "modeling.py"): b"# authored tiny backend is supplied by the test\n",
    }
    files = []
    paths = {}
    for (role, name), raw in payloads.items():
        path = {"model": model_directory, "code": code_directory}[role] / name
        path.write_bytes(raw)
        paths[(role, name)] = path
        files.append({"relative_to": role, "path": name, "bytes": len(raw), "sha256": sha(raw)})
    manifest_path = tmp_path / "assets.json"
    manifest_raw = json.dumps({"authored_protocol_only": True, "files": files},
                              sort_keys=True).encode()
    manifest_path.write_bytes(manifest_raw)
    assets = {"schema": reference._PROFILE.RECEIPT_SCHEMA, "status": "available",
              "profile_id": reference.PROFILE_ID, "manifest_sha256": sha(manifest_raw),
              "model_directory": str(model_directory), "code_directory": str(code_directory),
              "files": files, "unavailable_reasons": [], "proof_authority": False,
              "model_numerics_verified": False}
    inspections, loads = [], []
    tokenizer, model = TinyTokenizer(), TinyCompleteModel()

    def inspect(*args, **kwargs):
        inspections.append((args, kwargs))
        return deepcopy(assets)

    def load(observed):
        loads.append(deepcopy(observed))
        return torch, tokenizer, model, {
            "architecture": "NewForTokenClassification", "classifier_loaded": True,
            "classifier_logits_used_for_dense_embedding": False,
            "tensor_count": 3, "tensor_names": sorted(model.state_dict()),
            "missing_keys": [], "unexpected_keys": [], "mismatched_keys": [], "error_msgs": [],
        }

    monkeypatch.setattr(reference._PROFILE, "inspect_local_assets", inspect)
    monkeypatch.setattr(reference._PROFILE, "PUBLISHED_ASSETS", {
        (row["relative_to"], row["path"]): {"bytes": row["bytes"], "sha256": row["sha256"]}
        for row in files})
    monkeypatch.setattr(complete, "_load_backend", load)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    sessions = []
    arguments = dict(manifest_path=manifest_path, expected_manifest_sha256=sha(manifest_raw),
                     model_directory=model_directory, code_directory=code_directory)

    def open_session(**kwargs):
        session = subject.SourceEmbeddingDeviceSession768(**arguments, **kwargs)
        sessions.append(session)
        return session

    value = SimpleNamespace(open=open_session, tokenizer=tokenizer, model=model,
        paths=paths, manifest_path=manifest_path, arguments=arguments, assets=assets,
        inspections=inspections, loads=loads, sessions=sessions)
    yield value
    try:
        for session in sessions:
            try:
                session.close()
            except (ValueError, OSError):
                # Tamper controls deliberately make close refuse custody. Its
                # finally block must nevertheless close descriptors and tensors.
                assert session._closed
                assert session._custody.files == []
                assert session._model is None
    finally:
        torch.set_num_threads(previous_threads)


def sources():
    return [{"id": "one", "source_text": "Exact"},
            {"id": "two", "source_text": "二"}]


def test_real_tiny_cpu_forward_normalizes_and_binds_exact_source_receipts(environment):
    session = environment.open(optimized=False)
    rows = sources(); before = deepcopy(rows)
    result = session.infer(rows, batch_size=2)
    assert rows == before
    assert result["model_inference_executed"] is True
    assert result["actual_forward_batches"] == [{
        "rows": 2, "tokens_per_row": 7, "input_device": "cpu", "output_device": "cpu",
        "output_dtype": "torch.float32", "output_shape": [2, 7, 768], "native_forward_calls": 1}]
    assert result["dense_path_verification"]["native_forward_calls"] == 2
    assert result["dense_path_verification"]["bitwise_equal"] is True
    assert len(environment.model.calls) == 2  # Complete probe + actual inference; bare probe separate.
    assert len(result["receipts"]) == 2
    for row, receipt in zip(rows, result["receipts"]):
        assert receipt["id"] == row["id"]
        assert receipt["source_sha256"] == sha(row["source_text"].encode())
        assert receipt["token_input_sha256"] == reference._digest(
            [1] + [2] * len(row["source_text"]) + [3])
        assert receipt["embedding"][:2] == pytest.approx([0.6, 0.8])
        assert receipt["embedding"][2:] == [0.0] * 766
        assert math.hypot(*receipt["embedding"]) == pytest.approx(1)
        assert receipt["truncated"] is False and receipt["normalized"] is True
        assert receipt["asset_manifest_sha256"] == environment.arguments["expected_manifest_sha256"]
    assert all(value.device.type == "cpu" for value in environment.model.parameters())
    assert all(value.device.type == "cpu" for batch in environment.model.calls for value in batch.values())


def test_persistent_session_loads_backend_once_across_multiple_requests(environment):
    session = environment.open()
    first = session.infer(sources())
    second = session.infer(sources())
    assert len(environment.loads) == 1
    assert len(environment.inspections) == 1
    assert first["receipts"] == second["receipts"]
    assert first["dense_path_verification"] is not None
    assert second["dense_path_verification"] is None
    assert len(environment.model.calls) == 3


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_device_policy_requires_literal_boolean_before_loading(environment, value):
    with pytest.raises(ValueError):
        environment.open(optimized=value)
    assert environment.loads == []


@pytest.mark.parametrize("rows", [None, [], (), "source", [{"id": "x", "source_text": ""}],
    [{"id": "x", "source_text": " "}], [{"id": "x", "source_text": "a\x00b"}],
    [{"id": "x", "source_text": "\ud800"}], [{"id": "x", "source_text": "ok", "target": {}}],
    [{"id": "x", "source_text": "ok"}, {"id": "x", "source_text": "different"}],
    [{"id": "x" * 257, "source_text": "ok"}], [{"id": "x", "source_text": "a" * 65537}]])
def test_invalid_source_rows_refuse_without_forward(environment, rows):
    session = environment.open()
    with pytest.raises(ValueError):
        session.infer(rows)
    assert environment.model.calls == []


@pytest.mark.parametrize("batch_size", [True, False, 0, 17, 1.0, "1", None])
def test_invalid_batch_size_refuses_without_forward(environment, batch_size):
    session = environment.open()
    with pytest.raises(ValueError):
        session.infer(sources(), batch_size=batch_size)
    assert environment.model.calls == []


def test_every_source_is_token_admitted_before_first_forward(environment):
    session = environment.open()
    environment.tokenizer.lengths["late-overlong"] = 8193
    with pytest.raises(ValueError):
        session.infer(sources() + [{"id": "late", "source_text": "late-overlong"}], batch_size=1)
    assert environment.model.calls == []


@pytest.mark.parametrize("tokens", [[True], [-1], [32], [1.0], [], "tokens"])
def test_invalid_token_ids_refuse_without_forward(environment, tokens):
    session = environment.open()
    environment.tokenizer.bad_tokens = tokens
    with pytest.raises(ValueError):
        session.infer(sources())
    assert environment.model.calls == []


@pytest.mark.parametrize("defect", ["changed_token", "changed_mask", "left_padding",
    "extra_field", "missing_mask", "float_tokens", "non_tensor"])
def test_mutated_padding_never_returns_a_source_receipt(environment, defect):
    session = environment.open()
    environment.tokenizer.pad_defect = defect
    with pytest.raises((ValueError, TypeError)):
        session.infer(sources(), batch_size=2)


@pytest.mark.parametrize("defect", ["zero", "nan", "inf", "width", "dtype",
                                   "batch", "sequence", "missing"])
def test_invalid_real_forward_outputs_never_return_a_receipt(environment, defect):
    session = environment.open()
    environment.model.defect = defect
    with pytest.raises((ValueError, AttributeError)):
        session.infer(sources())


def test_model_weight_mutation_between_calls_refuses_before_forward(environment):
    session = environment.open()
    with torch.no_grad():
        environment.model.new.embedding.weight[0, 0] += 1
    with pytest.raises(ValueError):
        session.infer(sources())
    assert environment.model.calls == []


def test_model_weight_mutation_during_forward_prevents_success(environment):
    session = environment.open()
    def mutate():
        with torch.no_grad():
            environment.model.classifier.bias.add_(1)
    environment.model.forward_hook = mutate
    with pytest.raises(ValueError):
        session.infer(sources())
    assert len(environment.model.calls) == 2


@pytest.mark.parametrize("kind", ["write", "replace", "symlink", "missing"])
def test_asset_custody_changes_between_calls_refuse_without_forward(environment, kind):
    session = environment.open()
    path = environment.paths[("model", "model.safetensors")]
    original = path.read_bytes()
    if kind == "write":
        path.write_bytes(b"x" * len(original))
    elif kind == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(original); os.replace(replacement, path)
    elif kind == "symlink":
        replacement = path.with_suffix(".target")
        replacement.write_bytes(original); path.unlink(); path.symlink_to(replacement)
    else:
        path.unlink()
    with pytest.raises((ValueError, OSError)):
        session.infer(sources())
    assert environment.model.calls == []


def test_asset_write_during_forward_prevents_success(environment):
    session = environment.open()
    environment.model.forward_hook = lambda: environment.paths[("code", "modeling.py")].write_bytes(b"changed")
    with pytest.raises((ValueError, OSError)):
        session.infer(sources())
    assert len(environment.model.calls) == 2


def test_pre_cancelled_request_never_performs_a_forward(environment):
    session = environment.open(); cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        session.infer(sources(), cancel_event=cancel)
    assert environment.model.calls == []


def test_cancellation_after_one_batch_prevents_partial_success(environment):
    session = environment.open(); cancel = threading.Event()
    environment.model.forward_hook = cancel.set
    with pytest.raises(InterruptedError):
        session.infer(sources(), batch_size=1, cancel_event=cancel)
    assert len(environment.model.calls) == 2
    assert all(batch["input_ids"].shape[0] == 1 for batch in environment.model.calls)


@pytest.mark.parametrize("seconds", [True, False, 0, -1, 121, float("nan"), float("inf"), "120", None])
def test_invalid_deadline_refuses_without_forward(environment, seconds):
    session = environment.open()
    with pytest.raises(ValueError):
        session.infer(sources(), timeout_seconds=seconds)
    assert environment.model.calls == []


def test_closed_session_refuses_and_close_is_idempotent(environment):
    session = environment.open(); session.close(); session.close()
    with pytest.raises((ValueError, RuntimeError)):
        session.infer(sources())
    assert environment.model.calls == []


def test_other_thread_cannot_use_the_creating_threads_session(environment):
    session = environment.open(); failures = []
    def receive():
        try:
            session.infer(sources())
        except BaseException as error:
            failures.append(error)
    worker = threading.Thread(target=receive); worker.start(); worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], (ValueError, RuntimeError))
    assert environment.model.calls == []


def test_session_refuses_foreign_process_identity(environment, monkeypatch):
    session = environment.open(); pid = os.getpid()
    with monkeypatch.context() as local:
        local.setattr(subject.os, "getpid", lambda: pid + 1)
        with pytest.raises((ValueError, RuntimeError)):
            session.infer(sources())
    assert environment.model.calls == []


def test_reentrant_inference_is_refused_during_forward(environment):
    session = environment.open(); failures = []
    def reenter():
        try:
            session.infer(sources())
        except BaseException as error:
            failures.append(error)
    environment.model.forward_hook = reenter
    session.infer(sources())
    assert failures and all(isinstance(error, (ValueError, RuntimeError)) for error in failures)
    assert len(environment.model.calls) == 2


def test_limits_are_frozen_and_have_the_explicit_bounded_defaults():
    limits = subject.SourceEmbeddingDeviceLimits768()
    assert (limits.max_rows, limits.max_batch_size, limits.max_total_tokens,
            limits.max_padded_tokens, limits.max_attention_cells) == (128, 16, 32768, 8192, 8388608)
    with pytest.raises(FrozenInstanceError):
        limits.max_rows = 129


@pytest.mark.parametrize("field", ["max_rows", "max_batch_size", "max_total_tokens",
                                  "max_padded_tokens", "max_attention_cells"])
@pytest.mark.parametrize("bad", [True, 0, -1, 1.5])
def test_limits_require_real_positive_bounded_integers(field, bad):
    with pytest.raises(ValueError):
        replace(subject.SourceEmbeddingDeviceLimits768(), **{field: bad})


def test_source_count_limit_refuses_without_forward(environment):
    session = environment.open(limits=subject.SourceEmbeddingDeviceLimits768(max_rows=1))
    with pytest.raises(ValueError):
        session.infer(sources())
    assert environment.model.calls == []


def test_total_token_limit_refuses_without_forward(environment):
    session = environment.open(limits=subject.SourceEmbeddingDeviceLimits768(max_total_tokens=3))
    with pytest.raises(ValueError):
        session.infer(sources())
    assert environment.model.calls == []


def test_opt_out_stays_cpu_even_when_cuda_availability_is_reported(environment, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "current_device", lambda: pytest.fail("CPU opt-out queried CUDA device"))
    session = environment.open(optimized=False)
    result = session.infer(sources())
    assert result["profile"]["device"] == "cpu"
    assert result["cuda_executed"] is False


@pytest.mark.parametrize("optimized,available,expected", [
    (False, True, "cpu"), (True, False, "cpu"), (True, True, "cuda:2")])
def test_device_selection_is_protocol_only_without_cuda_tensor_execution(optimized, available, expected):
    fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available,
                                                current_device=lambda: 2))
    assert subject._device(fake, optimized) == expected


def test_device_session_receipts_have_distinct_profile_and_no_authority(environment):
    session = environment.open()
    result = session.infer(sources())
    assert result["schema"] == "gte-native-device-embedding-production/v1"
    assert result["profile_id"] != reference.PROFILE_ID
    assert result["profile"]["profile_id"] == result["profile_id"]
    description = session.describe()
    profile_preimage = {key: value for key, value in result["profile"].items()
                        if key != "profile_sha256"}
    profile_sha256 = sha(json.dumps(profile_preimage, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())
    assert result["profile"]["profile_sha256"] == profile_sha256
    assert description == result["profile"]
    assert result["complete_checkpoint_loading"] == {
        "architecture": "NewForTokenClassification", "classifier_loaded": True,
        "classifier_logits_used_for_dense_embedding": False,
        "tensor_count": 3, "tensor_names": sorted(environment.model.state_dict()),
        "missing_keys": [], "unexpected_keys": [], "mismatched_keys": [], "error_msgs": []}
    assert set(result["runtime_versions"]) == {
        "python", "torch", "transformers", "tokenizers", "safetensors"}
    assert all(type(value) is str and value for value in result["runtime_versions"].values())
    assert result["cuda_executed"] is False
    assert result["maximum_context_numerics_verified"] is False
    for field in ("training_executed", "download_executed", "ir_decoder_executed",
                  "source_semantics_verified", "proof_authority", "execution_authority",
                  "promotion_performed"):
        assert result[field] is False and result["profile"][field] is False
    assert result["vectors"] == [row["embedding"] for row in result["receipts"]]
    for receipt in result["receipts"]:
        assert receipt["schema"] == "gte-native-device-embedding-receipt/v1"
        assert receipt["profile_id"] == result["profile_id"]
        assert receipt["profile_sha256"] == profile_sha256
        assert receipt["device"] == "cpu" and receipt["dtype"] == "float32"
        assert receipt["embedding_sha256"] == sha(json.dumps(receipt["embedding"],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())


def test_model_nonpersistent_buffer_mutation_between_calls_is_rejected(environment):
    session = environment.open()
    environment.model.new.offset[0] = 1
    with pytest.raises(ValueError):
        session.infer(sources())
    assert environment.model.calls == []


def test_model_nonpersistent_buffer_mutation_during_forward_is_rejected(environment):
    session = environment.open()
    environment.model.forward_hook = lambda: environment.model.new.offset.add_(1)
    with pytest.raises(ValueError):
        session.infer(sources())
    assert len(environment.model.calls) == 2


def test_forward_cannot_substitute_tokens_after_source_receipt_binding(environment):
    session = environment.open()
    environment.model.defect = "input_substitution"
    with pytest.raises(ValueError):
        session.infer(sources())
    assert len(environment.model.calls) == 2


def test_late_cancellation_callback_asset_mutation_cannot_escape_closing_fence(environment):
    session = environment.open()
    class LateMutation:
        after_forward_checks = 0
        def is_set(self):
            if len(environment.model.calls) >= 2:
                self.after_forward_checks += 1
                if self.after_forward_checks == 2:
                    environment.paths[("code", "modeling.py")].write_bytes(b"late-callback-change")
            return False
    event = LateMutation()
    with pytest.raises((ValueError, OSError)):
        session.infer(sources(), cancel_event=event)
    assert event.after_forward_checks >= 2
    assert len(environment.model.calls) == 2


def test_deadline_expiring_after_forward_cannot_return_a_partial_success(environment, monkeypatch):
    session = environment.open(); now = [0.0]
    monkeypatch.setattr(subject.time, "monotonic", lambda: now[0])
    environment.model.forward_hook = lambda: now.__setitem__(0, 2.0)
    with pytest.raises(TimeoutError):
        session.infer(sources(), timeout_seconds=1)
    assert len(environment.model.calls) == 2


def test_cpu_autocast_is_refused_before_float32_profile_forward(environment):
    session = environment.open(optimized=False)
    with torch.autocast("cpu", dtype=torch.bfloat16):
        assert torch.is_autocast_enabled("cpu")
        with pytest.raises(ValueError):
            session.infer(sources())
    assert environment.model.calls == []


@pytest.mark.parametrize("limit", ["max_padded_tokens", "max_attention_cells"])
def test_all_batch_memory_budgets_are_admitted_before_forward(environment, limit):
    limits = replace(subject.SourceEmbeddingDeviceLimits768(), **{limit: 8})
    session = environment.open(limits=limits)
    with pytest.raises(ValueError):
        session.infer(sources(), batch_size=2)
    assert environment.model.calls == []


def test_custom_batch_ceiling_is_enforced_without_forward(environment):
    session = environment.open(limits=subject.SourceEmbeddingDeviceLimits768(max_batch_size=1))
    with pytest.raises(ValueError):
        session.infer(sources(), batch_size=2)
    assert environment.model.calls == []


@pytest.mark.parametrize("field,ceiling", [
    ("max_rows", 4096), ("max_batch_size", 16), ("max_total_tokens", 262144),
    ("max_padded_tokens", 131072), ("max_attention_cells", 67108864)])
def test_custom_limits_cannot_expand_past_native_admission_ceiling(field, ceiling):
    with pytest.raises(ValueError):
        replace(subject.SourceEmbeddingDeviceLimits768(), **{field: ceiling + 1})


@pytest.mark.parametrize("key", [("model", "config.json"), ("model", "tokenizer.json"),
                                 ("code", "configuration.py"), ("code", "modeling.py"), None])
def test_custody_covers_tokenizer_code_configuration_and_manifest(environment, key):
    session = environment.open()
    path = environment.paths[key] if key is not None else environment.manifest_path
    path.write_bytes(b"changed")
    with pytest.raises((ValueError, OSError)):
        session.describe()
    assert environment.model.calls == []


@pytest.mark.parametrize("kind", ["missing", "symlink", "hardlink"])
def test_constructor_rejects_missing_or_aliased_assets_before_loading(environment, kind):
    path = environment.paths[("model", "model.safetensors")]
    if kind == "missing":
        path.unlink()
    elif kind == "symlink":
        target = path.with_suffix(".target"); target.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(target)
    else:
        os.link(path, path.with_suffix(".alias"))
    with pytest.raises((ValueError, OSError)):
        environment.open()
    assert environment.loads == []


def test_constructor_requires_reserved_thread_policy_before_model_loading(environment):
    torch.set_num_threads(2)
    try:
        with pytest.raises(ValueError):
            environment.open()
        assert environment.loads == []
    finally:
        torch.set_num_threads(1)


def test_close_refusal_still_releases_every_owned_asset_descriptor(environment):
    session = environment.open()
    descriptors = [row[1] for row in session._custody.files]
    environment.paths[("model", "model.safetensors")].write_bytes(b"changed")
    with pytest.raises((ValueError, OSError)):
        session.close()
    assert session._closed and session._model is None and session._reference == {}
    assert session._buffer_reference == {} and session._tokenizer is None
    assert session._custody.files == []
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    session.close()


def test_context_exit_preserves_original_error_even_when_custody_refuses_close(environment):
    session = environment.open()
    original = RuntimeError("original authored failure")
    with pytest.raises(RuntimeError) as observed:
        with session:
            environment.paths[("code", "configuration.py")].write_bytes(b"changed")
            raise original
    assert observed.value is original
    assert session._closed and session._custody.files == []


def test_failed_operation_cannot_be_reused_for_a_later_success(environment):
    session = environment.open(); cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        session.infer(sources(), cancel_event=cancel)
    cancel.clear()
    with pytest.raises(ValueError):
        session.infer(sources(), cancel_event=cancel)
    assert environment.model.calls == []


def test_caller_limits_are_detached_and_cannot_change_admitted_budget_or_profile(environment):
    caller_limits = subject.SourceEmbeddingDeviceLimits768(max_rows=1)
    session = environment.open(limits=caller_limits)
    admitted_profile = session.describe()
    assert session._limits is not caller_limits
    assert session._limits == caller_limits
    object.__setattr__(caller_limits, "max_rows", 2)
    assert session._limits.max_rows == 1
    assert session.describe() == admitted_profile
    with pytest.raises(ValueError):
        session.infer(sources())
    assert environment.model.calls == []
    assert session.infer(sources()[:1])["profile"] == admitted_profile


def test_forged_exact_limits_are_revalidated_before_asset_admission_or_loading(environment):
    caller_limits = subject.SourceEmbeddingDeviceLimits768()
    object.__setattr__(caller_limits, "max_total_tokens", 0)
    with pytest.raises(ValueError):
        environment.open(limits=caller_limits)
    assert environment.inspections == []
    assert environment.loads == []


def test_flipping_pathlike_inputs_are_frozen_once_for_custody_inspection_and_loader(environment):
    first_paths = {key: environment.arguments[key]
                   for key in ("manifest_path", "model_directory", "code_directory")}
    class FlippingPath:
        def __init__(self, first):
            self.first = first
            self.calls = 0
        def __fspath__(self):
            self.calls += 1
            return str(self.first if self.calls == 1 else self.first.with_name("different-root"))
    supplied = {key: FlippingPath(path) for key, path in first_paths.items()}
    environment.arguments.update(supplied)
    session = environment.open()
    assert all(value.calls == 1 for value in supplied.values())
    args, kwargs = environment.inspections[0]
    assert args == (first_paths["manifest_path"],)
    assert isinstance(args[0], Path)
    assert kwargs["model_directory"] == first_paths["model_directory"]
    assert kwargs["code_directory"] == first_paths["code_directory"]
    assert all(isinstance(kwargs[key], Path) for key in ("model_directory", "code_directory"))
    assert environment.loads[0]["model_directory"] == str(first_paths["model_directory"])
    assert environment.loads[0]["code_directory"] == str(first_paths["code_directory"])
    assert {row[0] for row in session._custody.files} == {
        first_paths["manifest_path"], *environment.paths.values()}
    session.infer(sources())
    assert all(value.calls == 1 for value in supplied.values())


def test_invalid_manifest_sha_refuses_before_file_open_or_model_loader(environment, monkeypatch):
    environment.arguments["expected_manifest_sha256"] = "A" * 64
    monkeypatch.setattr(reference._PROFILE, "_open_file",
                        lambda path: pytest.fail("invalid manifest SHA reached file opening"))
    with pytest.raises(ValueError, match="lowercase SHA256"):
        environment.open()
    assert environment.inspections == []
    assert environment.loads == []
