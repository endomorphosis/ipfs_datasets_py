"""Bounded numerical protocol and post-fit canary checks without Torch work."""
from contextlib import contextmanager
from copy import deepcopy
import builtins
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import codebase_targets
from ipfs_datasets_py.logic.software_contracts import codebase_feature_worker as worker
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes


def target(index, offset=1, *, path=None, name=None, revision="snapshot:worker-fixture"):
    name = name or f"increment_{index}"
    source = f"def {name}(n: int) -> int:\n    return n + {offset}\n".encode()
    return codebase_targets.prepare_codebase_targets(source,
        IntegerOffsetContract(path or f"unit_{index}.py", name, "n", offset), revision=revision).to_dict()


@pytest.fixture(scope="module")
def template():
    training = [target(0, 1), target(1, 2)]
    runtime = runtimes.build_codebase_feature_runtime(training)
    return {"schema": worker.REQUEST_SCHEMA, "contract": runtime.contract.to_dict(),
            "feature_space": runtime.feature_space, "base_state": None,
            "training": training, "tuning": [target(2, 1)], "canary": [target(3, 1), target(4, 2)],
            "options": {"epochs": 2, "latent_width": 8, "learning_rate": .02,
                        "max_seconds": 10, "seed": 1729}}


@pytest.fixture
def request_data(template):
    return deepcopy(template)


@pytest.fixture
def no_torch(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            pytest.fail("invalid worker request reached Torch import")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.mark.parametrize("mutation", ["extra", "missing", "schema", "list"])
def test_request_schema_is_closed_before_numerical_work(request_data, no_torch, mutation):
    if mutation == "extra":
        request_data["qualified"] = True
    elif mutation == "missing":
        del request_data["canary"]
    elif mutation == "schema":
        request_data["schema"] = "another-worker@1"
    else:
        request_data = [request_data]
    with pytest.raises(ValueError, match="closed"):
        worker.execute(request_data)


def test_foreign_domain_is_rejected_before_torch(request_data, no_torch):
    request_data["contract"]["domain"] = "security_ir"
    with pytest.raises(ValueError):
        worker.execute(request_data)


@pytest.mark.parametrize("role", ["training", "tuning", "canary"])
@pytest.mark.parametrize("shape", ["empty", "too_many", "tuple"])
def test_each_role_has_a_bounded_nonempty_list(request_data, no_torch, role, shape):
    request_data[role] = {"empty": [], "too_many": request_data[role] * 17,
                          "tuple": tuple(request_data[role])}[shape]
    with pytest.raises(ValueError, match="bounded targets"):
        worker.execute(request_data)


def test_basis_width_cap_precedes_numerical_work(request_data, no_torch):
    request_data["feature_space"]["columns"] *= 513
    with pytest.raises(ValueError, match="basis"):
        worker.execute(request_data)


def test_direct_request_byte_cap_precedes_numerical_work(request_data, no_torch, monkeypatch):
    monkeypatch.setattr(worker, "MAX_BYTES", 64)
    with pytest.raises(ValueError, match="input.*bound"):
        worker.execute(request_data)


@pytest.mark.parametrize("space", [None, [], "basis", {"columns": []}, {"columns": ()}])
def test_basis_requires_a_nonempty_bounded_mapping(request_data, no_torch, space):
    request_data["feature_space"] = space
    with pytest.raises(ValueError, match="basis"):
        worker.execute(request_data)


def test_total_cohort_is_bounded_even_when_each_role_fits(request_data, no_torch):
    for offset, role in enumerate(("training", "tuning", "canary")):
        request_data[role] = [target(20 + offset * 11 + index) for index in range(11)]
    with pytest.raises(ValueError, match="32 bounded targets"):
        worker.execute(request_data)


@pytest.mark.parametrize("field", ["qualified", "admitted", "formalized"])
def test_target_authority_cannot_be_claimed(request_data, no_torch, field):
    request_data["training"][0][field] = True
    with pytest.raises(ValueError, match="qualification"):
        worker.execute(request_data)


@pytest.mark.parametrize("field", list(features.FALSE))
def test_feature_basis_authority_cannot_reach_torch(request_data, no_torch, field):
    request_data["feature_space"][field] = True
    with pytest.raises(ValueError):
        worker.execute(request_data)


@pytest.mark.parametrize("field", list(features.FALSE))
def test_numerical_parent_authority_cannot_reach_torch(request_data, no_torch, field):
    request_data["base_state"] = state_for(request_data)
    request_data["base_state"][field] = True
    with pytest.raises(ValueError):
        worker.execute(request_data)


def test_forged_semantic_target_rejects_even_with_valid_envelope_shape(request_data, no_torch):
    request_data["training"][0]["projections"][0]["expression"]["query_mode"] = "satisfiability"
    with pytest.raises(ValueError, match="producer replay"):
        worker.execute(request_data)


@pytest.mark.parametrize("role", ["training", "tuning", "canary"])
def test_duplicate_exact_target_cannot_cross_any_role(request_data, no_torch, role):
    if role == "training":
        request_data[role].append(deepcopy(request_data[role][0]))
    else:
        request_data[role] = [deepcopy(request_data["training"][0])]
    with pytest.raises(ValueError, match="duplicate|leakage|overlap"):
        worker.execute(request_data)


@pytest.mark.parametrize("revision,path", [
    ("snapshot:other", "unit_0.py"),
    ("snapshot:worker-fixture", "renamed.py"),
])
def test_same_raw_source_cannot_escape_roles_via_revision_or_path(request_data, no_torch, revision, path):
    request_data["canary"] = [target(0, path=path, revision=revision)]
    assert request_data["canary"][0]["source_digest"] != request_data["training"][0]["source_digest"]
    with pytest.raises(ValueError, match="duplicate|leakage|overlap"):
        worker.execute(request_data)


def test_same_source_path_cannot_escape_roles_by_renaming_function(request_data, no_torch):
    request_data["canary"] = [target(0, name="renamed_function", path="unit_0.py")]
    with pytest.raises(ValueError, match="duplicate|leakage|overlap"):
        worker.execute(request_data)


@pytest.mark.parametrize("key,value", [
    ("epochs", 0), ("epochs", 9), ("epochs", True), ("epochs", 1.0),
    ("latent_width", 8.0), ("latent_width", 4),
    ("learning_rate", 0), ("learning_rate", .11), ("learning_rate", True),
    ("learning_rate", float("nan")), ("learning_rate", float("inf")),
    ("max_seconds", 0), ("max_seconds", 121), ("max_seconds", True),
    ("max_seconds", float("nan")), ("seed", -1), ("seed", 2**31), ("seed", True),
])
def test_options_match_owner_bounds_before_torch(request_data, no_torch, key, value):
    request_data["options"][key] = value
    with pytest.raises(ValueError):
        worker.execute(request_data)


def test_options_cannot_add_runner_device_or_other_extra_key(request_data, no_torch):
    request_data["options"]["device"] = "cuda"
    with pytest.raises(ValueError, match="options"):
        worker.execute(request_data)


@pytest.mark.parametrize("role,index", [("training", 0), ("tuning", 2), ("canary", 3)])
def test_unseen_atoms_in_any_role_require_explicit_basis_migration(request_data, no_torch, role, index):
    request_data[role][0] = target(index, 3)
    with pytest.raises(ValueError, match="basis.migration"):
        worker.execute(request_data)


def state_for(request, *, epochs=0):
    width, latent = len(request["feature_space"]["columns"]), 8
    tensors = [[[0.] * latent for _ in range(width)], [0.] * latent,
               [[0.] * width for _ in range(latent)], [0.] * width]
    return {"schema": features.STATE_SCHEMA,
            "contract_sha256": request["contract"]["contract_sha256"]
                if "contract_sha256" in request["contract"] else
                runtimes.ModalityContract.from_dict(request["contract"]).sha256,
            "feature_space_sha256": features.digest(request["feature_space"]), "latent_width": latent,
            "parameters": tensors, "adam": [{"step": epochs, "exp_avg": deepcopy(value),
                "exp_avg_sq": deepcopy(value)} for value in tensors], "completed_epochs": epochs,
            "tuning_targets_sha256": features.digest(request["tuning"]),
            "optimizer_config": {"name": "Adam", "learning_rate": .02, "betas": [.9, .999], "eps": 1e-8},
            **features.FALSE}


def fake_numeric(monkeypatch, request, *, before_error=2., after_error=1.):
    calls = []
    threads = {"intra": 7, "inter": 7}
    fake = SimpleNamespace(__version__="test-protocol-no-numerical-work",
        set_num_threads=lambda count: threads.update(intra=count),
        set_num_interop_threads=lambda count: threads.update(inter=count),
        get_num_threads=lambda: threads["intra"], get_num_interop_threads=lambda: threads["inter"])
    monkeypatch.setitem(sys.modules, "torch", fake)
    after = state_for(request, epochs=1)
    def train(contract, space, training, tuning, **options):
        calls.append(("train", [row.source_digest for row in training], [row.source_digest for row in tuning]))
        assert options["base_state"] == request["base_state"]
        return {"state": after, "report": {**features.FALSE}}
    def infer(contract, space, state, rows):
        calls.append(("infer", state["completed_epochs"], [row.source_digest for row in rows]))
        matrix, ids, coverage = features._matrix(space, rows)
        error = after_error if state["completed_epochs"] == 1 else before_error
        return {"rows": [{"source_digest": identity, "reconstructed_projection_features": {
            name: [value + error for (projection, _), value in zip(space["columns"], vector) if projection == name]
            for name in space["projection_ids"]}} for identity, vector in zip(ids, matrix)],
            "coverage": coverage, **features.FALSE}
    monkeypatch.setattr(features, "train_projection_features", train)
    monkeypatch.setattr(features, "infer_projection_features", infer)
    return calls


@pytest.mark.parametrize("after_error,accepted", [(1., True), (2., True), (3., False)])
def test_canary_metric_is_postfit_and_cannot_feed_fit_or_tuning(request_data, monkeypatch, after_error, accepted):
    request_data["base_state"] = state_for(request_data)
    initial = features.digest(request_data)
    calls = fake_numeric(monkeypatch, request_data, after_error=after_error)
    result = worker.execute(request_data)
    projection = codebase_targets.PROJECTION_ID
    assert result["canary_before"]["mean_squared_error"][projection] == pytest.approx(4.)
    assert result["canary_after"]["mean_squared_error"][projection] == pytest.approx(after_error**2)
    assert result["canary_nonregression"] is accepted
    assert result["canary_gate"] == "parent_nonregression"
    assert calls[0] == ("train", [row["source_digest"] for row in request_data["training"]],
                        [row["source_digest"] for row in request_data["tuning"]])
    assert [call[0] for call in calls] == ["train", "infer", "infer"]
    assert all(call[2] == [row["source_digest"] for row in request_data["canary"]] for call in calls[1:])
    assert result["request_sha256"] == initial == features.digest(request_data)
    assert result["runtime"]["intraop_threads"] == result["runtime"]["interop_threads"] == 1
    assert result["runtime"]["device"] == "cpu"
    assert result["decoded_formulas_generated"] is False
    assert all(result[key] is False for key in features.FALSE)


def test_initial_canary_records_observation_without_inventing_prior_model(request_data, monkeypatch):
    calls = fake_numeric(monkeypatch, request_data)
    result = worker.execute(request_data)
    assert result["canary_before"] is None
    assert result["canary_after"]["mean_squared_error"][codebase_targets.PROJECTION_ID] == pytest.approx(1.)
    assert result["canary_nonregression"] is True
    assert result["canary_gate"] == "initial_baseline"
    assert [call[0] for call in calls] == ["train", "infer"]


def test_main_rejects_input_size_before_read_or_execute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker, "MAX_BYTES", 64)
    Path("request.json").write_bytes(b"x" * 65)
    monkeypatch.setattr(worker, "execute", lambda request: pytest.fail("oversized request executed"))
    with pytest.raises(ValueError, match="input.*bound"):
        worker.main()
    assert not Path("response.json").exists()


def test_main_rejects_request_growth_after_stat_without_unbounded_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker, "MAX_BYTES", 64)
    Path("request.json").write_bytes(b"{}")
    original = Path.open
    reads = []
    class GrowingInput(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert 0 <= size <= 65, "worker performed an unbounded input read"
            return super().read(size)
    @contextmanager
    def opened(path, *args, **kwargs):
        if path.name == "request.json":
            yield GrowingInput(b"x" * 65)
        else:
            with original(path, *args, **kwargs) as stream:
                yield stream
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(worker, "execute", lambda request: pytest.fail("growing request executed"))
    with pytest.raises(ValueError, match="bound"):
        worker.main()
    assert reads == [65]
    assert not Path("response.json").exists()


def test_main_bounds_output_and_leaves_no_partial_response(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker, "MAX_BYTES", 64)
    Path("request.json").write_text("{}")
    monkeypatch.setattr(worker, "execute", lambda request: {"payload": "x" * 65})
    with pytest.raises(ValueError, match="output.*bound"):
        worker.main()
    assert not Path("response.json").exists()


def test_main_roundtrips_closed_json_without_network_or_numerical_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("request.json").write_text('{"fixture":true}')
    def execute(request):
        assert request == {"fixture": True}
        return {"schema": worker.RESULT_SCHEMA, "qualified": False}
    monkeypatch.setattr(worker, "execute", execute)
    worker.main()
    assert json.loads(Path("response.json").read_bytes()) == {"schema": worker.RESULT_SCHEMA, "qualified": False}


def test_memory_metrics_use_bounded_native_worker_peaks_in_bytes(monkeypatch):
    raw = b"Name:\tpython\nVmHWM:\t256 kB\nVmPeak:\t2048 kB\nVmRSS:\t128 kB\nVmSize:\t1024 kB\n"
    reads = []
    class Status(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    def opened(path, mode):
        assert str(path) == "/proc/self/status" and mode == "rb"
        return Status(raw)
    monkeypatch.setattr(Path, "open", opened)
    metrics = worker._memory_observation()
    assert reads == [16385]
    assert metrics == {"measurement": "linux_proc_self_status", "scope": "worker_process_only",
        "phase": "after_training_before_response_serialization", "peak_resident_bytes": 256 * 1024,
        "peak_virtual_bytes": 2048 * 1024, "resident_bytes": 128 * 1024, "virtual_bytes": 1024 * 1024}


@pytest.mark.parametrize("payload", [
    None, b"", b"VmHWM: 1 MB\n", b"x" * 16385,
    b"VmHWM: 1 kB\nVmHWM: 2 kB\nVmPeak: 2 kB\nVmRSS: 1 kB\nVmSize: 2 kB\n",
])
def test_unavailable_or_invalid_memory_telemetry_cannot_invent_zero_peak(monkeypatch, payload):
    def opened(path, mode):
        if payload is None:
            raise OSError("proc telemetry unavailable")
        return io.BytesIO(payload)
    monkeypatch.setattr(Path, "open", opened)
    result = worker._memory_observation()
    assert result["measurement"] == "unavailable"
    assert all(result[key] is None for key in ("peak_resident_bytes", "peak_virtual_bytes", "resident_bytes", "virtual_bytes"))
