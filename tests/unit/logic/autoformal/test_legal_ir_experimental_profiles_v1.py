"""Portable source/identity and small CPU-constructor controls for six ports.

No historical checkpoint, dataset, training run, provider or Lean is required.
The preserved proposal bodies are independently pinned source oracles, never
imported as an artifact runtime or accepted as a caller validation authority.
"""
from __future__ import annotations

import ast
import builtins
from copy import deepcopy
import _io
import io
import os
import stat
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).absolute().parents[4]
PREFIX = "ipfs_datasets_py.logic.autoformal.experimental"
PROPOSALS = ROOT / "docs/autoformalization/proposals/patches"
SPECS = {
    "context_initialization": ("projected_context_decoder_v1", "context_initialization.patch", 22244,
        "de68e2ed3975c3ae27c6ed733fec7e1b162ffecc7d5a073280b40411eff3574d",
        "legal-ir-native-request-recovery-20261017-01/retained-legal-context-parity-20261018-v01/projected_context_decoder_v01.py"),
    "context_trained": ("trained_projected_context_decoder_v1", "context_trained.patch", 22018,
        "508e77f75061d0a0567577f025d69a2a6680a286c82e8679e9ae972b1b2e0cf2",
        "legal-ir-native-request-recovery-20261017-01/retained-legal-context-training-20261018-v01/trained_projected_context_decoder_v01.py"),
    "gated_conditioning": ("gated_conditioning_v1", "gated_conditioning.patch", 21788,
        "dd91a47e8c116ea2cb6daa60716f0c452b82585df78d4c88756a1147eb55ba00",
        "legal-ir-step-conditioning-20261018-01/gated_conditioning.py"),
    "gated_training_state": ("gated_training_state_v1", "gated_training_state.patch", 25068,
        "a1ad93184fbf417b704c801ce6c15b932f0d138974f4f020239c7cbb4e0493a3",
        "legal-ir-gated-training-state-20261018-01/training_state.py"),
    "journal_session": ("journal_training_session_v1", "journal_session.patch", 39666,
        "527159a86b380e81c376d80e8464aa79420b71ab13e471faa33a3e72442beffc",
        "legal-ir-journal-training-session-20261018-01/candidate/session.py"),
    "journal_inference": ("journal_inference_v1", "journal_inference.patch", 34369,
        "95295682fe80c4ffc0010fded4235b38e6633ba82a39e17267e8e757f50bd6a9",
        "legal-ir-journal-inference-20261018-01/candidate/runtime.py"),
}
CHANGED = {
    "context_initialization": {"_raw", "_implementation", "_validate", "_parent",
        "model_state", "build_from_real_parent", "load_with_real_parent"},
    "context_trained": {"_raw", "_implementation", "_validate"},
    "gated_conditioning": {"_sources"},
    "gated_training_state": {"_candidate", "_implementation", "_validate", "pack"},
    "journal_session": {"_owners", "_validate"},
    "journal_inference": {"_owners", "_validate_resume"},
}


@pytest.fixture
def owners(monkeypatch):
    # Skip broad package-root initializers, as in the existing focused fixtures.
    # These paths are the genuine installed owners, not alternative backends.
    parents = {
        "ipfs_datasets_py": ROOT / "ipfs_datasets_py",
        "ipfs_datasets_py.logic": ROOT / "ipfs_datasets_py/logic",
        "ipfs_datasets_py.logic.autoformal": ROOT / "ipfs_datasets_py/logic/autoformal",
        "ipfs_datasets_py.logic.formalization": ROOT / "ipfs_datasets_py/logic/formalization",
        "ipfs_datasets_py.logic.formalization.autoencoder": ROOT / "ipfs_datasets_py/logic/formalization/autoencoder",
        "ipfs_datasets_py.optimizers": ROOT / "ipfs_datasets_py/optimizers",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer": ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer",
    }
    before = set(sys.modules)
    for name, path in parents.items():
        if name not in sys.modules:
            module = types.ModuleType(name); module.__path__ = [str(path)]
            monkeypatch.setitem(sys.modules, name, module)
    result = {key: importlib.import_module(PREFIX + "." + spec[0]) for key, spec in SPECS.items()}
    result["bridge"] = importlib.import_module(PREFIX + "._legacy_source_bridge_v1")
    yield result
    for name in set(sys.modules) - before:
        if name.startswith("ipfs_datasets_py."):
            sys.modules.pop(name, None)


def original_source(key):
    _, patch, size, digest, _ = SPECS[key]
    raw = (PROPOSALS / patch).read_bytes()
    assert len(raw) <= 65536
    lines = raw.decode().splitlines(keepends=True)
    assert sum(line.startswith("@@ ") for line in lines) == 1
    source = "".join(line[1:] for line in lines if line.startswith("+") and not line.startswith("+++"))
    assert len(source.encode()) == size
    assert hashlib.sha256(source.encode()).hexdigest() == digest
    return source


@pytest.mark.parametrize("key", list(SPECS))
def test_retained_algorithms_and_constants_are_preserved(key):
    original = ast.parse(original_source(key))
    path = ROOT / "ipfs_datasets_py/logic/autoformal/experimental" / (SPECS[key][0] + ".py")
    current = ast.parse(path.read_bytes())
    defs = lambda tree: {node.name: node for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    old, new = defs(original), defs(current)
    added = {"source_profile_bridge"} | ({"_require_current_producer"} if key == "gated_training_state" else set())
    if key == "context_initialization":
        added.add("inspect_parent_source_compatibility")
    assert set(new) == set(old) | added
    for name in set(old) - CHANGED[key]:
        assert ast.dump(old[name]) == ast.dump(new[name]), name
    # These algorithms acquire only an early fixed-source gate. Prove the rest
    # is still the complete retained body, rather than excluding it wholesale.
    early_only = ({"_parent", "model_state", "build_from_real_parent", "load_with_real_parent"}
                  if key == "context_initialization" else {"_sources"} if key == "gated_conditioning" else set())
    for name in early_only:
        function = new[name]
        function.body = [node for node in function.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "_bridge"
            and node.value.func.attr in {"require_shared_source", "require_source"})]
        assert ast.dump(old[name]) == ast.dump(function), name
    if key == "gated_training_state":
        function = new["pack"]
        function.body = [node for node in function.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_require_current_producer")]
        assert ast.dump(old["pack"]) == ast.dump(function)
    assignments = lambda tree: {ast.unparse(node.targets[0]): ast.dump(node.value)
        for node in tree.body if isinstance(node, ast.Assign)}
    a, b = assignments(original), assignments(current)
    assert set(b) == set(a) | {"_PORTED_SOURCE_SHA256"}
    for name in a:
        assert a[name] == b[name], name


@pytest.mark.parametrize("key", list(SPECS))
def test_discovery_is_detached_explicit_and_does_not_load_torch(owners, monkeypatch, key):
    real = builtins.__import__
    def guard(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise AssertionError("discovery must not import Torch")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guard)
    report = owners[key].source_profile_bridge()
    assert report["schema"] == "legal-ir-experimental-source-profile-bridge/v1"
    assert report["legacy_source"]["sha256"] == SPECS[key][3]
    assert report["legacy_source"]["bytes"] == SPECS[key][2]
    assert report["legacy_source"]["artifact_relative_path"] == SPECS[key][4]
    assert report["status"] == "experimental"
    for flag in ("historical_paths_freshly_authenticated", "numerical_equivalence_qualified",
                 "checkpoint_replay_performed", "default_runtime_changed", "statutory_accuracy",
                 "training_qualified", "Lean_admission"):
        assert report[flag] is False
    raw = Path(report["packaged_source"]["path"]).read_bytes()
    assert len(raw) == report["packaged_source"]["bytes"]
    assert hashlib.sha256(raw).hexdigest() == report["packaged_source"]["sha256"]
    report["legacy_source"]["sha256"] = "0" * 64
    assert owners[key].source_profile_bridge()["legacy_source"]["sha256"] == SPECS[key][3]


def recipes(owners, key="context_initialization"):
    bridge = owners["bridge"]
    current = bridge.source_reference(key)
    legacy = {"path": "/retained/artifacts/" + SPECS[key][4], "bytes": SPECS[key][2], "sha256": SPECS[key][3]}
    expected = {"decoder_sha256": current["sha256"], "source": current,
                "source_profile_bridge_sha256": bridge.implementation_sha256()}
    offered = {"decoder_sha256": SPECS[key][3], "source": legacy}
    return offered, expected


@pytest.mark.parametrize("key", list(SPECS))
def test_exact_legacy_and_current_recipes_are_supported_without_opening_legacy_paths(owners, key):
    old, new = recipes(owners, key)
    assert not Path(old["source"]["path"]).exists()
    assert owners["bridge"].compatible_implementation(old, new) is True
    assert owners["bridge"].compatible_implementation(new, new) is True


@pytest.mark.parametrize("change", ["hash", "length", "boolean_length", "path", "extra", "mixed", "missing_bridge", "false_bridge", "legacy_with_bridge"])
def test_unknown_partial_or_mixed_producer_recipes_refuse(owners, change):
    old, new = recipes(owners)
    if change == "hash": old["decoder_sha256"] = "0" * 64
    elif change == "length": old["source"]["bytes"] += 1
    elif change == "boolean_length": old["source"]["bytes"] = True
    elif change == "path": old["source"]["path"] = "/invented/same-basename.py"
    elif change == "extra": old["claim"] = "qualified"
    elif change == "mixed": old["decoder_sha256"] = new["decoder_sha256"]
    elif change == "missing_bridge": old = {k: v for k, v in new.items() if k != "source_profile_bridge_sha256"}
    elif change == "false_bridge": old = dict(new, source_profile_bridge_sha256="0" * 64)
    else: old["source_profile_bridge_sha256"] = new["source_profile_bridge_sha256"]
    assert owners["bridge"].compatible_implementation(old, new) is False


def test_nested_complete_legacy_recipe_and_nested_generation_mixture(owners):
    old, new = recipes(owners, "journal_inference")
    child_old, child_new = recipes(owners, "journal_session")
    old["journal_implementation"] = child_old
    new["journal_implementation"] = child_new
    assert owners["bridge"].compatible_implementation(old, new) is True
    old["journal_implementation"] = child_new
    assert owners["bridge"].compatible_implementation(old, new) is False


@pytest.mark.parametrize("kind", ["cycle", "depth", "nodes", "utf8", "object", "key_subclass"])
def test_complete_metadata_bounds_precede_source_hashing(owners, monkeypatch, kind):
    old, new = recipes(owners)
    if kind == "cycle": old["cycle"] = old
    elif kind == "depth":
        tail = old
        for _ in range(34): tail["child"] = {}; tail = tail["child"]
    elif kind == "nodes": old["children"] = [None] * 10001
    elif kind == "utf8": old["text"] = "é" * 40000
    elif kind == "object": old["hook"] = object()
    else:
        class Key(str): pass
        old[Key("subclass")] = "value"
    def forbidden(*args, **kwargs): raise AssertionError("prehash bounds must refuse first")
    monkeypatch.setattr(hashlib, "sha256", forbidden)
    with pytest.raises(owners["bridge"].SourceProfileBridgeError):
        owners["bridge"].compatible_implementation(old, new)


def test_fixed_relative_state_and_journal_owners_ignore_experiment_module_registry(owners, monkeypatch):
    monkeypatch.setitem(sys.modules, "legal_ir_gated_conditioning_candidate", object())
    monkeypatch.setitem(sys.modules, "legal_ir_gated_training_state", object())
    monkeypatch.setitem(sys.modules, "legal_ir_journal_training_session", object())
    assert owners["gated_training_state"]._candidate() is owners["gated_conditioning"]
    subject, candidate, recipe = owners["journal_session"]._owners()
    assert subject is owners["gated_training_state"] and candidate is owners["gated_conditioning"]
    assert recipe["source_profile_bridge_sha256"] == owners["bridge"].implementation_sha256()
    assert owners["journal_inference"]._owners()[0] is owners["journal_session"]


def test_wrong_module_and_changed_imported_source_identity_refuse(owners):
    bridge = owners["bridge"]
    with pytest.raises(bridge.SourceProfileBridgeError):
        bridge.require_module("context_initialization", types.SimpleNamespace(__file__=owners["context_initialization"].__file__))
    with pytest.raises(bridge.SourceProfileBridgeError):
        bridge.require_source("context_initialization", "0" * 64)


@pytest.mark.parametrize("generation", ["legacy", "packaged"])
def test_training_pack_producer_boundary_never_relabels_historical_updates(owners, monkeypatch, generation):
    state = owners["gated_training_state"]
    current = state._implementation()
    def forbidden(): raise AssertionError("producer policy must not allocate model or optimizer")
    monkeypatch.setattr(state, "_numeric", forbidden)
    if generation == "packaged":
        state._require_current_producer(current)
    else:
        historical = {"training_state_sha256": SPECS["gated_training_state"][3],
                      "gated_candidate_sha256": SPECS["gated_conditioning"][3],
                      "canonical_owners": current["canonical_owners"]}
        with pytest.raises(state.TrainingStateError, match="separately versioned continuation"):
            state._require_current_producer(historical)


@pytest.mark.parametrize("operation", ["parent", "build", "load", "model_state"])
def test_fixed_source_gate_precedes_caller_source_and_model_callbacks(owners, operation):
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError("caller source/model hook must not run")
    module = owners["context_initialization"]
    with pytest.raises(owners["bridge"].SourceProfileBridgeError):
        if operation == "parent": module._parent(Forbidden(), Forbidden(), {}, "0" * 64)
        elif operation == "build": module.build_from_real_parent(Forbidden(), Forbidden(), {}, Forbidden(), parent_file_sha256="0" * 64)
        elif operation == "load": module.load_with_real_parent(Forbidden(), Forbidden(), {}, {}, parent_file_sha256="0" * 64)
        else: module.model_state(Forbidden(), Forbidden(), Forbidden())


@pytest.mark.parametrize("steps,cadence", [(True, 2), (2, 2), (4, 2), (3, True), (3, 1), (3, 3)])
def test_journal_budget_remains_hard_three_cadence_two(owners, steps, cadence):
    with pytest.raises(owners["journal_session"].JournalTrainingError):
        owners["journal_session"]._policy(steps, cadence)


def test_journal_policy_preserves_cumulative_caller_owned_checkpoint_contract(owners):
    policy = owners["journal_session"]._policy(3, 2)
    assert policy["max_steps_from_legacy_anchor"] == 3 and policy["checkpoint_cadence"] == 2
    assert policy["physical_budgets_carry_across_resume"] is True
    assert policy["journal_is_not_a_recovery_point"] is True
    assert policy["checkpoint_durability_owned_by_caller"] is True
    assert policy["maximum_unrecorded_transition_tail"] == 1


@pytest.mark.parametrize("report,emitted,expected", [
    ({"status": "complete", "allowed_token_ids": [], "reason": None}, 1, ("complete", None)),
    ({"status": "invalid", "allowed_token_ids": [], "reason": "invalid_prefix"}, 1, ("blocked", "invalid_prefix")),
    ({"status": "partial", "allowed_token_ids": [3], "reason": None}, 64, ("step_budget_exhausted", "max_new_tokens_reached")),
    ({"status": "partial", "allowed_token_ids": [3], "reason": None}, 63, ("continuable", None)),
])
def test_model_only_serving_completion_and_bos64_boundaries(owners, report, emitted, expected):
    assert owners["journal_inference"]._status(report, emitted) == expected
    assert owners["journal_inference"].MAX_TOKENS == 64
    assert owners["journal_inference"].ROWS == ("fictional-retention", "fictional-inspection")


@pytest.mark.parametrize("profile", ["gated_training_state", "journal_session", "journal_inference"])
def test_malformed_public_checkpoint_refuses_before_torch_import(owners, monkeypatch, profile):
    real = builtins.__import__
    def guard(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise AssertionError("malformed checkpoint must refuse before numerical allocation")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guard)
    if profile == "gated_training_state":
        with pytest.raises(owners[profile].TrainingStateError): owners[profile].inspect({})
    elif profile == "journal_session":
        with pytest.raises(owners[profile].JournalTrainingError): owners[profile].prepare({}, expected_sha="0" * 64)
    else:
        with pytest.raises(owners[profile].JournalInferenceError): owners[profile].inspect({}, expected_sha="0" * 64)


def test_context_constructor_full_tensor_inventory_and_target_free_forward(owners):
    # Small CPU-only authored constructor control, not retained checkpoint replay.
    import torch
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        module = owners["context_initialization"]
        rng = torch.get_rng_state().clone()
        model = module._model(torch, 5, 1729)
        assert torch.equal(rng, torch.get_rng_state())
        state = model.state_dict()
        pristine = {name: value.detach().clone() for name, value in state.items()}
        assert len(state) == 13
        assert {name: tuple(value.shape) for name, value in state.items()} == module._shapes(5, True)
        assert tuple(state["decoder.weight_ih_l0"].shape) == (96, 400)
        latent = torch.zeros((1, 384), dtype=torch.float32)
        prefix = torch.tensor([[1, 3]], dtype=torch.long)
        with torch.inference_mode():
            projected, logits = model(latent, prefix)
            direct, _ = model.next_logits(prefix, model.start(projected), projected)
        assert tuple(logits.shape) == (1, 2, 5) and torch.equal(logits, direct)
        assert all(torch.equal(value, model.state_dict()[name]) for name, value in pristine.items())
    finally:
        torch.set_num_threads(previous)


def test_gated_projection_preserves_seed_rng_and_thirteen_to_fifteen_geometry(owners):
    import torch
    module = owners["gated_conditioning"]
    before = torch.get_rng_state().clone()
    projection = module._projection(torch)
    assert torch.equal(before, torch.get_rng_state())
    assert tuple(projection.weight.shape) == (8, 384) and projection.bias is None
    assert len(module.BODY_SHAPES) == 13 and len(module.SHAPES) == 15
    assert module.SHAPES["gate"] == ()
    assert module.SHAPES["source_to_embedding.weight"] == (8, 384)
    assert owners["gated_training_state"]._shapes("h0_only") == module.BODY_SHAPES
    assert owners["gated_training_state"]._shapes("gated_per_step") == module.SHAPES


@pytest.mark.parametrize("arm", ["h0_only", "gated_per_step"])
def test_complete_real_model_and_fresh_adam_export_without_claimed_updates(owners, arm):
    import torch
    numerical = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula")
    gated, state = owners["gated_conditioning"], owners["gated_training_state"]
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        body = numerical._model({"dimension": 384}, {"target_vocabulary": [str(i) for i in range(537)]}, gated.CONFIG)
        if arm == "gated_per_step":
            class AuthoredGatedTopology(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.gate = torch.nn.Parameter(torch.zeros((), dtype=torch.float32, device="cpu"))
                    self.body = body
                    self.source_to_embedding = gated._projection(torch)
            model = AuthoredGatedTopology()
        else:
            model = body
        options = dict(state.ADAM_DEFAULTS); options["betas"] = tuple(options["betas"])
        optimizer = torch.optim.Adam(model.parameters(), **options)
        expected = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        actual, moments = state._export(model, optimizer, arm, 0, torch)
        assert actual == expected
        assert list(actual) == list(state._shapes(arm))
        assert len(actual) == (13 if arm == "h0_only" else 15)
        assert moments == {"schema": "named-adam-state/v1", "parameters": {}}
        assert len(optimizer.state) == 0
        # An untouched real optimizer cannot substantiate even one update.
        with pytest.raises(state.TrainingStateError):
            state._export(model, optimizer, arm, 1, torch)
    finally:
        torch.set_num_threads(previous)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 0.1])
def test_context_exact_finite_float32_state_refusals(owners, value):
    import torch
    with pytest.raises(ValueError):
        owners["context_initialization"]._tensor(torch, [value], (1,), "control")


@pytest.fixture
def source_metadata_only(owners, monkeypatch):
    """Genuine owner metadata with framework imports and data-file opens denied.

    Like the existing owner fixture, path-only namespace containers skip broad
    package initialization. No owner function, implementation recipe or source
    validator is substituted. Python code imports may read canonical package
    or stdlib code plus four genuine CID dependency roots and typing_extensions.
    Explicit reads allow package .py files, the pinned retained gated proposal
    and two authenticated CID support tables. Artifact,
    workspace, checkpoint and dataset bodies are outside this read boundary.
    """
    package = ROOT / "ipfs_datasets_py"
    # tree_pin imports this genuine parser through an otherwise broad package.
    for name, path in (
        ("ipfs_datasets_py.logic.deontic", package / "logic/deontic"),
        ("ipfs_datasets_py.logic.deontic.utils", package / "logic/deontic/utils"),
    ):
        if name not in sys.modules:
            namespace = types.ModuleType(name); namespace.__path__ = [str(path)]
            monkeypatch.setitem(sys.modules, name, namespace)
    real_import, real_module = builtins.__import__, importlib.import_module
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    real_code_open = _io.open_code
    stdlib = Path(sys.base_prefix) / "lib" / ("python" + str(sys.version_info.major) + "." + str(sys.version_info.minor))
    proposal = PROPOSALS / "gated_conditioning.patch"
    # CID production is genuinely reached by the canonical compiler metadata
    # import. Permit its finite pure-Python dependency code, never the enclosing
    # site-packages directory or arbitrary resource files beneath these roots.
    cid_roots = {}
    for name in ("multiformats", "bases", "typing_validation", "multiformats_config"):
        spec = importlib.util.find_spec(name)
        if spec is None:
            continue  # Genuine owners retain their own optional-dependency behavior.
        assert type(spec.origin) is str
        origin = Path(spec.origin).absolute()
        assert origin.name == "__init__.py" and origin.parent.name == name
        assert origin.resolve() == origin and origin.is_file()
        cid_roots[name] = origin.parent
    extensions_spec = importlib.util.find_spec("typing_extensions")
    cid_singletons = set()
    if extensions_spec is not None:
        assert type(extensions_spec.origin) is str
        extensions_source = Path(extensions_spec.origin).absolute()
        assert extensions_source.name == "typing_extensions.py"
        assert extensions_source.resolve() == extensions_source and extensions_source.is_file()
        cid_singletons = {extensions_source, Path(importlib.util.cache_from_source(str(extensions_source)))}
    # The installed unchanged CID owner loads these two finite package tables.
    # Exact lengths and SHA256 values are source-support metadata, independent
    # of any legal corpus, checkpoint, embedding population or source dataset.
    cid_tables = ({
        cid_roots["multiformats_config"] / "multicodec-table.json":
            (90766, "289d9e9bd1394da3c2e8da7164e2c9af0c6802d219cad6fec763f8c7de1d9d31"),
        cid_roots["multiformats_config"] / "multibase-table.json":
            (3908, "f8a6ca3892c6140c7909ef67ed50e8da593ff34fa77d3f858a72f4a02da3d4a7"),
    } if "multiformats_config" in cid_roots else {})
    reads = []
    blocked = {"torch", "numpy", "tensorflow", "jax", "transformers",
               "sentence_transformers", "symai", "symbolicai"}

    def checked_path(value, *, code=False):
        assert isinstance(value, (str, bytes, os.PathLike)), "source path required; arbitrary descriptors denied"
        path = Path(os.fsdecode(value)).absolute()
        resolved = path.resolve()
        assert path == resolved, "aliased metadata input denied"
        if code:
            package_code = package in path.parents and path.suffix in {".py", ".pyc"}
            stdlib_code = (stdlib in path.parents and "site-packages" not in path.parts
                           and "dist-packages" not in path.parts and path.suffix in {".py", ".pyc"})
            cid_code = (path.suffix in {".py", ".pyc"}
                        and (any(root in path.parents for root in cid_roots.values()) or path in cid_singletons))
            assert package_code or stdlib_code or cid_code, "only canonical package/stdlib/declared CID code imports permitted"
        else:
            if path in cid_tables:
                expected_bytes, expected_sha256 = cid_tables[path]
                before = path.lstat()
                assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == expected_bytes
                # Authenticate this exact support file before handing the real
                # unchanged CID loader its ordinary read stream. Captured IO is
                # used only for this closed two-path authentication operation.
                with real_io_open(path, "rb") as stream:
                    raw = stream.read(expected_bytes + 1)
                after = path.lstat()
                witness = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_nlink,
                                       row.st_size, row.st_mtime_ns, row.st_ctime_ns)
                assert witness(before) == witness(after) and len(raw) == expected_bytes
                assert hashlib.sha256(raw).hexdigest() == expected_sha256
            else:
                assert ((package in path.parents and path.suffix == ".py") or path == proposal), \
                    "only declared source/support files may be read; data bodies denied"
            reads.append(path)
        return path

    def read_open(original, file, mode="r", *args, **kwargs):
        assert mode in ("r", "rb", "rt"), "metadata controls permit reads only"
        checked_path(file)
        return original(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND), \
            "metadata controls permit reads only"
        checked_path(path)
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_import(name, *args, **kwargs):
        assert name.split(".", 1)[0] not in blocked, "numerical/provider framework import denied"
        return real_import(name, *args, **kwargs)

    def guarded_module(name, *args, **kwargs):
        assert name.split(".", 1)[0] not in blocked, "numerical/provider framework import denied"
        return real_module(name, *args, **kwargs)

    def guarded_code_open(path):
        checked_path(path, code=True)
        return real_code_open(path)

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "__import__", guarded_import)
        guard.setattr(importlib, "import_module", guarded_module)
        guard.setattr(builtins, "open", lambda file, mode="r", *a, **k: read_open(real_open, file, mode, *a, **k))
        guard.setattr(io, "open", lambda file, mode="r", *a, **k: read_open(real_io_open, file, mode, *a, **k))
        guard.setattr(os, "open", guarded_os_open)
        guard.setattr(_io, "open_code", guarded_code_open)
        guard.setattr(io, "open_code", guarded_code_open)
        guard.setattr(sys, "dont_write_bytecode", True)
        # Prove the two public import routes and ordinary data-file opens are
        # fenced, even if a prior CPU control has already imported Torch.
        for import_call in (lambda: builtins.__import__("torch"), lambda: importlib.import_module("numpy")):
            with pytest.raises(AssertionError, match="framework import denied"):
                import_call()
        for open_call in (
            lambda: builtins.open(ROOT / "workspace/forbidden-checkpoint.json", "rb"),
            lambda: (ROOT / "artifacts/forbidden-dataset.json").read_bytes(),
            lambda: os.open(ROOT / "workspace/forbidden-checkpoint.json", os.O_RDONLY),
        ):
            with pytest.raises(AssertionError, match="data bodies denied"):
                open_call()
        # Code permission never grants general data permission in a CID root,
        # and the narrow code roots never grant sibling site-packages imports.
        for name in ("multiformats", "multiformats_config"):
            if name in cid_roots:
                with pytest.raises(AssertionError, match="data bodies denied"):
                    (cid_roots[name] / "unregistered-checkpoint-or-table.json").read_bytes()
        for root in cid_roots.values():
            with pytest.raises(AssertionError, match="declared CID code imports permitted"):
                _io.open_code(str(root.parent / "unregistered_dependency" / "module.py"))
        yield owners, reads


def _genuine_owner_recipe(owners, profile):
    """Call real current recipe owners, rather than rebuilding their metadata."""
    if profile in ("context_initialization", "context_trained"):
        source = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2")
        if profile == "context_initialization":
            return owners[profile]._implementation(source)
        return owners[profile]._implementation(source, owners["context_initialization"])
    if profile == "gated_training_state":
        return owners[profile]._implementation()
    if profile == "journal_session":
        return owners[profile]._owners()[2]
    assert profile == "journal_inference"
    return owners[profile]._owners()[-1]


def _registered_legacy_owner_recipe(owners, offered):
    """Translate only six independently pinned proposal identities, never data.

    SPECS above binds the retained proposal hashes/lengths/path suffixes. Current
    descriptors are measured from actual canonical owners. Shared descriptors,
    scalar values and list order are copied unchanged; no product compatibility
    function is used to generate this independent expected legacy recipe.
    """
    current, legacy = {}, {}
    for key, (_, _, size, digest, suffix) in SPECS.items():
        path = Path(owners[key].__file__).absolute()
        raw = path.read_bytes()
        current[key] = {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        legacy[key] = {"path": "/retained/artifacts/" + suffix, "bytes": size, "sha256": digest}
    scalar_fields = {
        "context_decoder_sha256": "context_initialization",
        "trained_context_decoder_sha256": "context_trained",
        "initial_context_decoder_sha256": "context_initialization",
        "training_state_sha256": "gated_training_state",
        "gated_candidate_sha256": "gated_conditioning",
    }
    translated = set()
    def visit(value, field=None):
        if type(value) is dict:
            for key, descriptor in current.items():
                if value == descriptor:
                    translated.add(key)
                    return deepcopy(legacy[key])
            result = {}
            for key, child in value.items():
                if key == "source_profile_bridge_sha256":
                    assert child == owners["bridge"].implementation_sha256()
                    continue
                result[key] = visit(child, key)
            return result
        if type(value) is list:
            return [visit(child) for child in value]
        if field in scalar_fields:
            key = scalar_fields[field]
            assert value == current[key]["sha256"]
            translated.add(key)
            return legacy[key]["sha256"]
        return deepcopy(value)
    return visit(offered), translated


@pytest.mark.parametrize("profile,expected_sources", [
    ("context_initialization", {"context_initialization"}),
    ("context_trained", {"context_initialization", "context_trained"}),
    ("gated_training_state", {"gated_conditioning", "gated_training_state"}),
    ("journal_session", {"gated_conditioning", "gated_training_state", "journal_session"}),
    ("journal_inference", {"gated_conditioning", "gated_training_state", "journal_session", "journal_inference"}),
], ids=["context_initialization", "context_trained", "gated_training_state", "journal_session", "journal_inference"])
def test_genuine_complete_owner_recipes_support_only_registered_generations(source_metadata_only, profile, expected_sources):
    owners, reads = source_metadata_only
    current = _genuine_owner_recipe(owners, profile)
    pristine = deepcopy(current)
    historical, translated = _registered_legacy_owner_recipe(owners, current)
    assert translated == expected_sources and historical != current
    assert owners["bridge"].compatible_implementation(current, current) is True
    assert owners["bridge"].compatible_implementation(historical, current) is True
    assert current == pristine and reads


def test_genuine_journal_nested_mixed_generations_refuse(source_metadata_only):
    owners, _ = source_metadata_only
    current = _genuine_owner_recipe(owners, "journal_inference")
    historical, _ = _registered_legacy_owner_recipe(owners, current)
    for outer, child in ((historical, current), (current, historical)):
        mixed = deepcopy(outer)
        mixed["journal_implementation"] = deepcopy(child["journal_implementation"])
        assert owners["bridge"].compatible_implementation(mixed, current) is False


@pytest.mark.parametrize("field", ["path", "sha256"])
def test_genuine_owner_shared_source_descriptors_remain_exact(source_metadata_only, field):
    owners, _ = source_metadata_only
    current = _genuine_owner_recipe(owners, "journal_session")
    historical, _ = _registered_legacy_owner_recipe(owners, current)
    assert current["canonical_owners"] == historical["canonical_owners"]
    for recipe in (current, historical):
        changed = deepcopy(recipe)
        shared = changed["canonical_owners"][0]
        assert shared["owner"] == "head"
        shared[field] = shared[field] + ".different" if field == "path" else "0" * 64
        assert owners["bridge"].compatible_implementation(changed, current) is False


def test_genuine_inference_public_grammar_and_selector_descriptors_remain_exact(source_metadata_only):
    owners, _ = source_metadata_only
    current = _genuine_owner_recipe(owners, "journal_inference")
    historical, _ = _registered_legacy_owner_recipe(owners, current)
    assert [Path(row["path"]).name for row in current["public_owners"]] == [
        "legal_compact_content_tokens_v1.py", "legal_compact_content_selection_v1.py"]
    assert current["public_owners"] == historical["public_owners"]
    for recipe in (current, historical):
        for index in range(2):
            for field in ("path", "sha256"):
                changed = deepcopy(recipe)
                public = changed["public_owners"][index]
                public[field] = public[field] + ".different" if field == "path" else "0" * 64
                assert owners["bridge"].compatible_implementation(changed, current) is False


def test_genuine_gated_migration_recipe_retains_original_list_contract(source_metadata_only):
    owners, _ = source_metadata_only
    tree = ast.parse(original_source("gated_conditioning"))
    original_specs = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SPECS" for target in node.targets)))
    actual = owners["gated_conditioning"]._sources()
    assert type(actual) is list and len(actual) == len(original_specs) == 4
    for row, (key, relative, digest) in zip(actual, original_specs, strict=True):
        path = ROOT / "ipfs_datasets_py" / relative
        raw = path.read_bytes()
        assert row == {"owner": key, "path": str(path), "bytes": len(raw), "sha256": digest}
        assert hashlib.sha256(raw).hexdigest() == digest
        assert "source_profile_bridge_sha256" not in row
    # This legacy-format shared-owner list is intentionally outside the dict
    # producer bridge. It remains the exact capsule contract, not a self-hash
    # recipe whose schema could be changed merely to make this test pass.
    assert owners["bridge"].compatible_implementation(actual, actual) is False


# Optional retained-state qualification. Ordinary unit collection skips both
# cases unless an admitted caller enrolls the exact assets and owned exports.
# Historical paths below are data in that caller's manifest, never code imports.
_RETAINED_GATED_PINS = {
    "h0_only": {
        "step1": (4550874, "3c78c231b6072d5120930ee324c664b161985bc44075512b41f7df82f532e566"),
        "step2": (4550873, "06ef08d3594aa83294f82216203c914f3283e8e1f2a3527e34107c4d8efce276"),
        "step2_report": (1578612, "39f8ed6257f09ac458f9812308770ebc27f5302eaa170068739fb779487ba0d3"),
    },
    "gated_per_step": {
        "step1": (4748956, "a1ac1d157b34815ff16869424c55cf36e7ed7c7dc8eb4bdb61c0b8d2218b9f38"),
        "step2": (4863232, "9016987b9f477762a857a02df3648cd43e40f596995b997e7b31be74d85e180a"),
        "step2_report": (1775324, "d665c343b962ce47dbadcce2e2a5977048368815710c0cec71ca552c75ec3cea"),
    },
}
_RETAINED_GATED_BODY_SHAPES = {
    "projection_down.weight": (4, 384), "projection_down.bias": (4,),
    "projection_up.weight": (384, 4), "projection_up.bias": (384,),
    "condition.weight": (8, 384), "condition.bias": (8,),
    "target_embedding.weight": (537, 8), "decoder.weight_ih_l0": (24, 8),
    "decoder.weight_hh_l0": (24, 8), "decoder.bias_ih_l0": (24,),
    "decoder.bias_hh_l0": (24,), "output.weight": (537, 8), "output.bias": (537,),
}


def _retained_gated_wire(value):
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _retained_gated_json(raw):
    import json
    import math
    def pairs(items):
        value = {}
        for key, item in items:
            assert type(key) is str and key not in value, "duplicate JSON key"
            value[key] = item
        return value
    def integer(text):
        value = int(text)
        assert -(2**63) <= value < 2**63, "bounded JSON integer required"
        return value
    def real(text):
        value = float(text)
        assert math.isfinite(value), "finite JSON number required"
        return value
    def invalid(text):
        raise AssertionError("nonfinite JSON constant refused: " + text)
    value = json.loads(raw, object_pairs_hook=pairs, parse_int=integer,
                       parse_float=real, parse_constant=invalid)
    remaining, pending = 1000000, [(value, 0)]
    while pending:
        item, depth = pending.pop(); remaining -= 1
        assert remaining >= 0 and depth <= 48, "bounded JSON graph required"
        assert type(item) in (dict, list, str, int, float, bool, type(None))
        if type(item) is dict:
            assert all(type(key) is str for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def _retained_gated_read(path, size, digest, maximum):
    assert type(path) is str and "\x00" not in path
    path = Path(path)
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert type(size) is int and 0 < size <= maximum
    assert type(digest) is str and len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)
    witness = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                            info.st_uid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
    assert before.st_uid == os.getuid() and before.st_size == size
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        assert witness(opened) == witness(before)
        raw = stream.read(maximum + 1)
        assert witness(os.fstat(stream.fileno())) == witness(opened)
    assert witness(path.lstat()) == witness(before) and len(raw) == size
    assert hashlib.sha256(raw).hexdigest() == digest
    return raw


@pytest.fixture
def retained_gated_assets():
    names = ("LEGAL_IR_RETAINED_GATED_ASSET_MANIFEST",
             "LEGAL_IR_RETAINED_GATED_ASSET_MANIFEST_SHA256",
             "LEGAL_IR_RETAINED_GATED_EXPORTS")
    values = [os.environ.get(name) for name in names]
    if not any(values):
        pytest.skip("retained gated replay requires an admitted frozen asset manifest")
    assert all(type(value) is str and value for value in values), "complete replay enrollment required"
    manifest_path, manifest_sha, exports_path = values
    manifest_size = Path(manifest_path).lstat().st_size
    raw = _retained_gated_read(manifest_path, manifest_size, manifest_sha, 16384)
    manifest = _retained_gated_json(raw)
    assert type(manifest) is dict and set(manifest) == {"schema", "arms"}
    assert manifest["schema"] == "legal-ir-retained-gated-replay-assets/v1"
    assert type(manifest["arms"]) is dict and set(manifest["arms"]) == set(_RETAINED_GATED_PINS)
    evidence = ROOT / "workspace/test-logs/federal-corpus-audits"
    # Authenticate every enrolled raw file before parsing any checkpoint or
    # report. Both cases see the same closed six-member historical input set.
    authenticated = {}
    for arm, pins in _RETAINED_GATED_PINS.items():
        descriptors = manifest["arms"][arm]
        assert type(descriptors) is dict and set(descriptors) == set(pins)
        authenticated[arm] = {}
        for role, (size, digest) in pins.items():
            descriptor = descriptors[role]
            assert type(descriptor) is dict and set(descriptor) == {"path", "bytes", "sha256"}
            assert type(descriptor["bytes"]) is int and descriptor["bytes"] == size
            assert descriptor["sha256"] == digest
            assert evidence in Path(descriptor["path"]).parents
            authenticated[arm][role] = _retained_gated_read(descriptor["path"], size, digest, 8 * 1024**2)
    exports = Path(exports_path)
    assert exports.is_absolute() and exports.resolve(strict=True) == exports
    info = exports.lstat()
    assert evidence in exports.parents and stat.S_ISDIR(info.st_mode)
    assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
    return manifest, manifest_sha, authenticated, exports, (info.st_dev, info.st_ino)


def _retained_gated_state(torch, model, optimizer, checkpoint, arm):
    """Independent full parameter and named-Adam comparison; no owner export."""
    shapes = (_RETAINED_GATED_BODY_SHAPES if arm == "h0_only" else {
        "gate": (), **{"body." + name: shape for name, shape in _RETAINED_GATED_BODY_SHAPES.items()},
        "source_to_embedding.weight": (8, 384)})
    parameters, tensors = dict(model.named_parameters()), model.state_dict()
    assert list(parameters) == list(tensors) == list(shapes) == checkpoint["parameter_order"]
    assert len(parameters) == (13 if arm == "h0_only" else 15)
    assert set(parameters.values()) == set(optimizer.state)
    assert len(optimizer.param_groups) == 1
    group = optimizer.param_groups[0]
    expected_options = {"lr": 0.001, "betas": [0.9, 0.999], "eps": 1e-8,
        "weight_decay": 0, "amsgrad": False, "maximize": False, "foreach": False,
        "capturable": False, "differentiable": False, "fused": None, "decoupled_weight_decay": False}
    assert set(group) == set(expected_options) | {"params"}
    assert {key: list(value) if key == "betas" else value for key, value in group.items()
            if key != "params"} == expected_options
    assert len(group["params"]) == len(parameters)
    assert all(actual is wanted for actual, wanted in zip(group["params"], parameters.values(), strict=True))
    weights, moments = {}, {}
    for name, parameter in parameters.items():
        assert tuple(parameter.shape) == tuple(tensors[name].shape) == shapes[name]
        assert parameter.device.type == "cpu" and parameter.dtype is torch.float32
        assert parameter.requires_grad is True and parameter.grad is None
        assert bool(torch.isfinite(parameter).all())
        expected = torch.tensor(checkpoint["model_state"][name], dtype=torch.float32, device="cpu")
        assert torch.equal(parameter.detach(), expected) and torch.equal(tensors[name], expected)
        weights[name] = parameter.detach().tolist()
        observed, saved = optimizer.state[parameter], checkpoint["optimizer_state"]["parameters"][name]
        assert type(observed) is dict and set(observed) == set(saved) == {"step", "exp_avg", "exp_avg_sq"}
        step = observed["step"]
        assert tuple(step.shape) == () and step.device.type == "cpu" and step.dtype is torch.float32
        assert float(step) == saved["step"] == checkpoint["progress"]["optimizer_steps"]
        moments[name] = {"step": int(step)}
        for key in ("exp_avg", "exp_avg_sq"):
            tensor = observed[key]
            assert tuple(tensor.shape) == shapes[name] and tensor.device.type == "cpu"
            assert tensor.dtype is torch.float32 and tensor.requires_grad is False
            assert bool(torch.isfinite(tensor).all())
            assert key != "exp_avg_sq" or bool((tensor >= 0).all())
            assert torch.equal(tensor, torch.tensor(saved[key], dtype=torch.float32, device="cpu"))
            moments[name][key] = tensor.detach().tolist()
    named = {"schema": "named-adam-state/v1", "parameters": moments}
    assert _retained_gated_wire(weights) == _retained_gated_wire(checkpoint["model_state"])
    assert _retained_gated_wire(named) == _retained_gated_wire(checkpoint["optimizer_state"])
    assert hashlib.sha256(_retained_gated_wire(weights)).hexdigest() == checkpoint["weights_sha256"]
    assert hashlib.sha256(_retained_gated_wire(named)).hexdigest() == checkpoint["optimizer_state_sha256"]
    return {"tensor_count": len(weights), "parameter_count": sum(value.numel() for value in parameters.values()),
            "weights_sha256": checkpoint["weights_sha256"], "optimizer_state_sha256": checkpoint["optimizer_state_sha256"],
            "progress": deepcopy(checkpoint["progress"])}


def _retained_gated_save(exports, identity, arm, report):
    """Exclusively persist one bounded direct-child report in owned exports."""
    raw = _retained_gated_wire(report) + b"\n"
    assert 0 < len(raw) <= 2 * 1024**2
    info = exports.lstat()
    assert (info.st_dev, info.st_ino) == identity and stat.S_ISDIR(info.st_mode)
    assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
    directory = os.open(exports, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(directory)
        assert (opened.st_dev, opened.st_ino) == identity
        name = arm + "-retained-replay.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        with os.fdopen(os.open(name, flags, 0o600, dir_fd=directory), "wb") as stream:
            assert stream.write(raw) == len(raw)
            stream.flush(); os.fsync(stream.fileno())
        os.fsync(directory)
        assert (exports.lstat().st_dev, exports.lstat().st_ino) == identity
        assert _retained_gated_read(str(exports / name), len(raw), hashlib.sha256(raw).hexdigest(), 2 * 1024**2) == raw
    finally:
        os.close(directory)


@pytest.mark.parametrize("arm", ["h0_only", "gated_per_step"])
def test_retained_gated_checkpoint_state_and_saved_logits(retained_gated_assets, owners, monkeypatch, arm):
    """Two restores and one original-mode saved-prefix forward per arm.

    The saved step2 report records PRE-update logits from step1 weights. The
    final step2 checkpoint is separately restored and checked without a forward.
    No update, backward, generation, legal or held-out evaluation is performed.
    """
    manifest, manifest_sha, authenticated, exports, export_identity = retained_gated_assets
    values = {role: _retained_gated_json(raw) for role, raw in authenticated[arm].items()}
    originals = {role: _retained_gated_wire(value) for role, value in values.items()}
    first, final, oracle = values["step1"], values["step2"], values["step2_report"]
    for checkpoint, steps in ((first, 1), (final, 2)):
        assert checkpoint["schema"] == "legal-gated-matched-training-checkpoint/v1" and checkpoint["arm"] == arm
        assert checkpoint["progress"] == {"optimizer_steps": steps, "epochs_completed": steps // 2, "row_cursor": steps % 2}
    token = lambda value: hashlib.sha256(_retained_gated_wire(value)).hexdigest()
    assert oracle["schema"] == "legal-gated-matched-training-step/v1" and oracle["arm"] == arm
    assert oracle["new_step"] == 2 and oracle["resume"] is False
    assert oracle["before_checkpoint_sha256"] == token(first) and oracle["after_checkpoint_sha256"] == token(final)
    assert oracle["before_model_state_sha256"] == first["weights_sha256"]
    assert oracle["after_model_state_sha256"] == final["weights_sha256"]
    assert oracle["before_Adam_state_sha256"] == first["optimizer_state_sha256"]
    assert oracle["after_Adam_state_sha256"] == final["optimizer_state_sha256"]
    assert oracle["output_shape"] == [1, 46, 537] and oracle["training_exposed"] is True
    assert oracle["source_encoder_authenticated"] is False and oracle["new_evaluation_or_generation_forwards"] == 0
    row = first["population"]["rows"][1]
    assert row == final["population"]["rows"][1] and row["id"] == oracle["row_id"] == "fictional-inspection"
    assert len(row["target_ids"]) == 47 and row["target_ids"] == oracle["target_ids"]
    assert oracle["offered_ids"] == row["target_ids"][:-1] and oracle["label_ids"] == row["target_ids"][1:]
    assert token(oracle["full_sequence_logits"]) == oracle["full_sequence_logits_sha256"]

    # The canonical compiler reaches this genuine parser through broad package
    # initializers; preserve the same namespace-only focused import boundary.
    for name, path in (("ipfs_datasets_py.logic.deontic", ROOT / "ipfs_datasets_py/logic/deontic"),
                       ("ipfs_datasets_py.logic.deontic.utils", ROOT / "ipfs_datasets_py/logic/deontic/utils")):
        if name not in sys.modules:
            namespace = types.ModuleType(name); namespace.__path__ = [str(path)]
            monkeypatch.setitem(sys.modules, name, namespace)
    import torch
    state, gated = owners["gated_training_state"], owners["gated_conditioning"]
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    counts = {"restore_calls": 0, "Adam_allocations": 0, "overlapping_Optimizer_base_allocations": 0,
              "GRU_forwards": 0, "GRU_pre_hooks": 0, "GRU_post_hooks": 0, "forbidden_calls": 0}
    active, handles, restored = {"phase": "preflight", "decoder": None}, [], []
    rng = torch.get_rng_state().clone()
    try:
        assert not torch.cuda.is_initialized() and not torch.is_inference_mode_enabled()
        assert not torch.is_autocast_enabled("cpu") and torch.get_default_dtype() is torch.float32
        assert torch.get_default_device().type == "cpu"
        runtime = gated.runtime_metadata()
        assert runtime == first["runtime"] == final["runtime"], "recorded CPU runtime required before allocation"
        # Adam lazily loads Dynamo's genuine API rules. Initialize them before
        # test sentinels can alias autograd.grad and backward to one function.
        importlib.import_module("torch._dynamo")
        assert torch.equal(rng, torch.get_rng_state())
        real_adam, real_base, real_gru = torch.optim.Adam.__init__, torch.optim.Optimizer.__init__, torch.nn.GRU.forward
        def forbidden(*args, **kwargs):
            counts["forbidden_calls"] += 1
            raise AssertionError("retained replay forbids backward, optimizer updates and generation")
        def adam_init(optimizer, *args, **kwargs):
            assert active["phase"] == "restore" and counts["Adam_allocations"] < 2
            counts["Adam_allocations"] += 1
            return real_adam(optimizer, *args, **kwargs)
        def base_init(optimizer, *args, **kwargs):
            assert type(optimizer) is torch.optim.Adam and active["phase"] == "restore"
            assert counts["overlapping_Optimizer_base_allocations"] + 1 == counts["Adam_allocations"]
            counts["overlapping_Optimizer_base_allocations"] += 1
            return real_base(optimizer, *args, **kwargs)
        def pre_hook(module, args):
            assert active["phase"] == "oracle_forward" and module is active["decoder"]
            assert counts["GRU_pre_hooks"] == counts["GRU_forwards"] == 0
            assert len(args) == 2 and tuple(args[0].shape) == (1, 46, 8) and tuple(args[1].shape) == (1, 1, 8)
            assert module.training is True and torch.is_grad_enabled() is True
            counts["GRU_pre_hooks"] += 1
        def gru_forward(module, *args, **kwargs):
            assert active["phase"] == "oracle_forward" and module is active["decoder"]
            assert counts["GRU_pre_hooks"] == 1 and counts["GRU_forwards"] == 0
            counts["GRU_forwards"] += 1
            return real_gru(module, *args, **kwargs)
        def post_hook(module, args, output):
            assert module is active["decoder"] and counts["GRU_forwards"] == 1
            assert counts["GRU_post_hooks"] == 0 and tuple(output[0].shape) == (1, 46, 8)
            counts["GRU_post_hooks"] += 1
        monkeypatch.setattr(torch.optim.Adam, "__init__", adam_init)
        monkeypatch.setattr(torch.optim.Optimizer, "__init__", base_init)
        monkeypatch.setattr(torch.nn.GRU, "forward", gru_forward)
        monkeypatch.setattr(torch.optim.Adam, "step", forbidden)
        monkeypatch.setattr(torch.Tensor, "backward", forbidden)
        monkeypatch.setattr(torch.autograd, "backward", forbidden)
        monkeypatch.setattr(torch.autograd, "grad", forbidden)
        monkeypatch.setattr(owners["journal_inference"], "prepare", forbidden)
        numerical = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula")
        for name in ("train", "infer", "project", "_metrics", "_restore"):
            monkeypatch.setattr(numerical, name, forbidden)
        for name in ("_decode", "infer"):
            monkeypatch.setattr(numerical.LatentFormulaDecoder, name, forbidden)
        shared = gated._owners(numerical=True)
        for owner, names in ((shared["runtime"], ("_forward", "generate_compact_content_trained_v2")),
                             (shared["head"], ("_forward",)),
                             (shared["trainer"], ("_restore", "train_compact_content_v2", "build_compact_content_training_v2"))):
            for name in names:
                monkeypatch.setattr(owner, name, forbidden)
        before = []
        for checkpoint in (first, final):
            inspection = state.inspect(checkpoint)
            assert inspection["progress"] == checkpoint["progress"] and inspection["checkpoint_sha256"] == token(checkpoint)
            active["phase"] = "restore"; counts["restore_calls"] += 1
            model, optimizer = state.restore(checkpoint)
            restored.append((model, optimizer))
            active["phase"] = "verify"
            before.append(_retained_gated_state(torch, model, optimizer, checkpoint, arm))
            assert torch.equal(rng, torch.get_rng_state()) and gated.runtime_metadata() == runtime
        model, optimizer = restored[0]
        decoder = model.decoder if arm == "h0_only" else model.body.decoder
        assert type(decoder) is torch.nn.GRU and decoder.dropout == 0 and decoder.num_layers == 1
        active["decoder"] = decoder
        handles.extend((decoder.register_forward_pre_hook(pre_hook), decoder.register_forward_hook(post_hook)))
        vector = torch.tensor([row["conditioning"]], dtype=torch.float32, device="cpu")
        prefix = torch.tensor([oracle["offered_ids"]], dtype=torch.long, device="cpu")
        expected = torch.tensor(oracle["full_sequence_logits"], dtype=torch.float32, device="cpu")
        assert tuple(expected.shape) == (1, 46, 537) and bool(torch.isfinite(expected).all())
        model.train()
        assert all(module.training is True for module in model.modules())
        assert all(parameter.grad is None for parameter in model.parameters())
        active["phase"] = "oracle_forward"
        # Preserve original model.train() + ordinary grad-enabled dispatch.
        # no_grad/inference_mode can choose a different native GRU path.
        with torch.enable_grad():
            projected, logits = model(vector, prefix)
        active["phase"] = "verify"
        assert tuple(projected.shape) == (1, 384) and tuple(logits.shape) == (1, 46, 537)
        assert bool(torch.isfinite(logits).all()) and torch.equal(logits.detach(), expected)
        full_sequence_logits = logits.detach().tolist()
        actual_logits_sha = token(full_sequence_logits)
        assert actual_logits_sha == oracle["full_sequence_logits_sha256"]
        assert [_retained_gated_state(torch, instance, adam, checkpoint, arm)
                for (instance, adam), checkpoint in zip(restored, (first, final), strict=True)] == before
        assert torch.equal(rng, torch.get_rng_state()) and gated.runtime_metadata() == runtime
        assert {role: _retained_gated_wire(value) for role, value in values.items()} == originals
        assert counts == {"restore_calls": 2, "Adam_allocations": 2, "overlapping_Optimizer_base_allocations": 2,
                          "GRU_forwards": 1, "GRU_pre_hooks": 1, "GRU_post_hooks": 1, "forbidden_calls": 0}
        for descriptors in manifest["arms"].values():
            for descriptor in descriptors.values():
                _retained_gated_read(descriptor["path"], descriptor["bytes"], descriptor["sha256"], 8 * 1024**2)
        report = {"schema": "legal-ir-retained-gated-replay-result/v1", "status": "passed", "arm": arm,
            "asset_manifest_sha256": manifest_sha, "assets": manifest["arms"][arm], "runtime": runtime,
            "checkpoints": before, "actual_counts": counts, "backwards": 0, "optimizer_updates": 0,
            "generation_calls": 0, "saved_step2_logits_use_step1_weights": True,
            "forward_training_mode": True, "forward_grad_enabled": True, "logit_shape": [1, 46, 537],
            "logits_exact_equal": True, "logits_sha256": actual_logits_sha, "tolerance_used": False,
            "full_sequence_logits": full_sequence_logits,
            "logit_difference": {"scalar_count": 24702, "changed_coordinates": 0,
                                 "maximum_absolute_difference": 0.0, "L2_difference": 0.0},
            "caller_JSON_RNG_model_and_Adam_unchanged": True, "progress_restored_as_metadata_only": True,
            "legacy_producer_unchanged": True, "new_checkpoint_packed": False,
            "training_exposed": True, "source_encoder_authenticated": False,
            "statutory_accuracy": False, "heldout_accuracy": False, "graph_admission": False, "Lean_admission": False}
        _retained_gated_save(exports, export_identity, arm, report)
    finally:
        for handle in handles:
            handle.remove()
        restored.clear()
        torch.set_num_threads(previous_threads)


def _source_preflight_parent():
    """Authored envelope with deliberately absent numerical qualification."""
    source = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2")
    parent = {
        "schema": source.SCHEMA, "domain_id": "legal_ir", "dimension": 384,
        "architecture": "authored-unqualified-metadata-envelope",
        "codec": {}, "config": {}, "implementation": source._implementation(),
        "parent_sha256": "1" * 64, "parent_binding": {}, "lineage": {},
        "model_state": {}, "weights_sha256": "2" * 64, "input_transform": {},
        "semantic_paths": [], "training_manifest": [], "validation_manifest": [],
        "training": {}, **source.FALSE,
    }
    return source, parent


def test_parent_source_preflight_compatible_metadata_does_not_qualify_empty_weights(source_metadata_only):
    owners, _ = source_metadata_only
    source, parent = _source_preflight_parent()
    pristine = deepcopy(parent)
    report = owners["context_initialization"].inspect_parent_source_compatibility(
        source, parent, expected_checkpoint_sha256=source.digest(parent))
    assert report["schema"] == "legal-ir-parent-source-compatibility/v1"
    assert report["scope"] == "source_implementation_metadata_only"
    assert report["compatible"] is True and report["mismatches"] == []
    assert report["checkpoint_canonical_sha256"] == source.digest(parent)
    assert report["expected_implementation_sha256"] == report["current_implementation_sha256"]
    for flag in ("weights_checked", "tensor_shapes_checked", "numerical_execution_performed",
                 "checkpoint_load_qualified", *source.FALSE):
        assert report[flag] is False
    assert parent == pristine


def test_parent_source_preflight_identifies_two_exact_nested_mismatches(source_metadata_only):
    owners, _ = source_metadata_only
    source, parent = _source_preflight_parent()
    current = deepcopy(parent["implementation"])
    parent["implementation"]["numerical"]["files"]["tree_pin.py"] = "0" * 64
    parent["implementation"]["native"]["dependencies"]["ipfs_datasets_py.logic.ui_ux_ir.decoder"] = "1" * 64
    report = owners["context_initialization"].inspect_parent_source_compatibility(
        source, parent, expected_checkpoint_sha256=source.digest(parent))
    assert report["compatible"] is False
    assert report["mismatches"] == [
        {"field_path": ["implementation", "native", "dependencies", "ipfs_datasets_py.logic.ui_ux_ir.decoder"],
         "expected": "1" * 64, "current": current["native"]["dependencies"]["ipfs_datasets_py.logic.ui_ux_ir.decoder"]},
        {"field_path": ["implementation", "numerical", "files", "tree_pin.py"],
         "expected": "0" * 64, "current": current["numerical"]["files"]["tree_pin.py"]},
    ]
    assert report["expected_implementation_sha256"] == source.digest(parent["implementation"])
    assert report["current_implementation_sha256"] == source.digest(current)
    report["mismatches"][0]["field_path"].append("caller-mutation")
    assert parent["implementation"]["native"]["dependencies"] == {
        **current["native"]["dependencies"], "ipfs_datasets_py.logic.ui_ux_ir.decoder": "1" * 64}


@pytest.mark.parametrize("digest", [True, "invalid", "0" * 64], ids=["boolean", "malformed", "wrong"])
def test_parent_source_preflight_requires_expected_canonical_digest(source_metadata_only, digest):
    owners, _ = source_metadata_only
    source, parent = _source_preflight_parent()
    with pytest.raises(ValueError, match="SHA256|digest differs"):
        owners["context_initialization"].inspect_parent_source_compatibility(
            source, parent, expected_checkpoint_sha256=digest)


@pytest.mark.parametrize("change", ["extra_envelope", "boolean_dimension", "authority",
                                   "scalar_state", "missing_identity", "extra_identity",
                                   "boolean_identity", "malformed_identity"])
def test_parent_source_preflight_refuses_malformed_envelopes_and_identities(source_metadata_only, change):
    owners, _ = source_metadata_only
    source, parent = _source_preflight_parent()
    if change == "extra_envelope": parent["extra"] = None
    elif change == "boolean_dimension": parent["dimension"] = True
    elif change == "authority": parent["qualified"] = True
    elif change == "scalar_state": parent["model_state"] = 0
    elif change == "missing_identity": parent["implementation"].pop("runtime_sha256")
    elif change == "extra_identity": parent["implementation"]["extra"] = "0" * 64
    elif change == "boolean_identity": parent["implementation"]["runtime_sha256"] = True
    else: parent["implementation"]["runtime_sha256"] = "invalid"
    with pytest.raises(ValueError):
        owners["context_initialization"].inspect_parent_source_compatibility(
            source, parent, expected_checkpoint_sha256=source.digest(parent))


@pytest.mark.parametrize("kind", ["cycle", "depth", "nodes", "string", "bytes", "integer",
                                "nonfinite", "object", "metaclass", "key_subclass"])
def test_parent_source_preflight_bounds_ordinary_json_before_serialization(source_metadata_only, kind):
    owners, _ = source_metadata_only
    source, parent = _source_preflight_parent()
    if kind == "cycle": parent["model_state"]["cycle"] = parent
    elif kind == "depth":
        tail = parent["model_state"]
        for _ in range(66):
            tail["child"] = {}; tail = tail["child"]
    elif kind == "nodes": parent["model_state"]["values"] = [None] * 500001
    elif kind == "string": parent["model_state"]["value"] = "x" * 65537
    elif kind == "bytes": parent["model_state"]["values"] = ["x" * 65536] * 129
    elif kind == "integer": parent["model_state"]["value"] = 2**64
    elif kind == "nonfinite": parent["model_state"]["value"] = float("nan")
    elif kind == "object": parent["model_state"]["value"] = object()
    elif kind == "metaclass":
        class RejectTypeEquality(type):
            def __eq__(cls, other):
                raise AssertionError("caller type equality hook must not run")
        class Forbidden(metaclass=RejectTypeEquality):
            pass
        parent["model_state"]["value"] = Forbidden()
    else:
        class Key(str):
            pass
        parent["model_state"][Key("value")] = None
    # The offered digest is well formed but would fail after serialization.
    # Each malformed graph must instead fail at the bounded plain-JSON gate.
    with pytest.raises(ValueError, match="JSON"):
        owners["context_initialization"].inspect_parent_source_compatibility(
            source, parent, expected_checkpoint_sha256="0" * 64)


def test_parent_source_preflight_rejects_caller_owner_before_callbacks(owners):
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError("caller source hook must not run")
    with pytest.raises(owners["bridge"].SourceProfileBridgeError):
        owners["context_initialization"].inspect_parent_source_compatibility(
            Forbidden(), {}, expected_checkpoint_sha256="0" * 64)
