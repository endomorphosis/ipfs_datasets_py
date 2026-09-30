"""The shared v2 factory exposes a read-only decoder without training migration."""
import copy
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features_v2 as streamed


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


decoder = (_load(os.environ["NATIVE_FORMAL_DECODER_PATH"], PREFIX + ".native_formal_decoder")
           if os.environ.get("NATIVE_FORMAL_DECODER_PATH") else importlib.import_module(PREFIX + ".native_formal_decoder"))
runtime_api = (_load(os.environ["AUTOENCODER_RUNTIME_MODULE_PATH"], PREFIX + ".autoencoder_runtime_registry")
               if os.environ.get("AUTOENCODER_RUNTIME_MODULE_PATH") else importlib.import_module(PREFIX + ".autoencoder_runtime_registry"))
fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py", "_v2_factory_fixtures")


def test_shared_v2_factory_decodes_without_training_and_requires_an_explicit_head():
    targets, tune = [fixtures._ui(1), fixtures._ui(2)], [fixtures._ui(3)]
    basis = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], targets)
    target_hash = hashlib.sha256()
    for target in targets:
        streamed.update_target_digest(target_hash, target)
    space = streamed.build_streamed_feature_space(domain="ui_ux_ir", projection_ids=basis["projection_ids"],
        projections=basis["projections"], columns=basis["columns"], training_sources=basis["training_sources"],
        excluded_projection_ids=basis["excluded_projection_ids"], training_targets_sha256=target_hash.hexdigest())
    head = decoder.train_formal_decoder(space, targets)
    train_matrix, train_ids, _ = features._matrix(space, targets)
    tune_matrix, tune_ids, _ = features._matrix(space, tune)
    result = streamed.train_streamed_projection_features(space, train_matrix, train_ids, tune_matrix, tune_ids,
        minibatch_size=1, tuning_targets_sha256="b" * 64, epochs=16, latent_width=4, max_seconds=30)
    state = copy.deepcopy(result["state"])
    factory = runtime_api.open_formal_decoder("ui_ux_ir", "native_v2", feature_space=space, state=state)
    before = factory.infer(targets)
    missing = factory.decode_formal_logic(targets)
    assert missing["status"] == "decoder_head_required" and not missing["decoded_formulas_generated"]
    decoded = factory.decode_formal_logic(targets, decoder_head=head)
    assert decoded["decoded_projection_count"] == 2
    assert decoded["model_inference"] == before
    assert not decoded["training_executed"]
    assert not factory.describe()["decoder_head_present"]  # Explicit override did not mutate the session.
    assert not hasattr(factory, "train") and not hasattr(factory, "register_candidate")
    state["parameters"][3] = [0.0] * len(state["parameters"][3])
    assert factory.infer(targets) == before  # Construction detached caller-owned state.
    bound = runtime_api.open_formal_decoder("ui_ux_ir", "native_v2", feature_space=space,
                                           state=result["state"], decoder_head=head)
    assert bound.decode_formal_logic(targets)["rows"] == decoded["rows"]
    with pytest.raises(runtime_api.RuntimeVersionError, match="another domain"):
        runtime_api.open_formal_decoder("security_ir", "native_v2", feature_space=space,
                                       state=result["state"], decoder_head=head)
    with pytest.raises(runtime_api.RuntimeVersionError, match="not implemented"):
        runtime_api.open_runtime("ui_ux_ir", "native_v2", feature_space=space, state=result["state"])
