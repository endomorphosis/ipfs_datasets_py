"""Legal inference acceleration without changing checkpoint identities."""
from __future__ import annotations

import hashlib
from pathlib import Path
from contextlib import nullcontext
from functools import wraps
from types import FunctionType, SimpleNamespace

from . import legal_384_package as package
from .checkpoint_hub import HubAutoencoder


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()


def _blas_limits():
    # Some CPU builds use an OpenMP BLAS pool that torch.set_num_threads does
    # not control. Keep this optional, and restore all pools on context exit.
    try:
        from threadpoolctl import threadpool_limits
    except ModuleNotFoundError as error:
        if error.name != "threadpoolctl":
            raise
        return nullcontext()
    return threadpool_limits(limits=1, user_api="blas")


def _cpu_inference(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        from ....optimizers.logic_theorem_optimizer.domain_384_autoencoder import _cpu
        # Share the original runtime lock for both global thread settings.
        with _cpu(), _blas_limits():
            return function(*args, **kwargs)
    return bounded


def _rows(rows, embedding_contract):
    """Use original row validation and sample construction with cached cues."""
    from ....optimizers.logic_theorem_optimizer.legal_modal_parser_inference import build_parser
    current, joint, formula = package._modules()
    parser = build_parser()
    adapter = SimpleNamespace(build_sample=lambda **options: current.build_sample(parser=parser, **options))
    original = package._rows
    # The sample builder already accepts a parser explicitly. Keep the signed
    # row builder's exact code/validation, and supply that dependency through a
    # private module adapter; no module attribute or global regex state changes.
    namespace = original.__globals__.copy()
    namespace["_modules"] = lambda: (adapter, joint, formula)
    build = FunctionType(original.__code__, namespace, original.__name__,
                         original.__defaults__, original.__closure__)
    return build(rows, embedding_contract)


class OptimizedRuntime:
    """Reuse the verified package, with separately identified inference code.

    Original core/source/weight checks still run at request boundaries. The
    package and its formula head retain their original bytes and identities.
    Batched float32 recurrence can slightly change decision margins. Public
    Legal loaders select this implementation by default; optimized=False
    selects the original runtime.
    """
    @_cpu_inference
    def __init__(self, runtime):
        from ....optimizers.logic_theorem_optimizer.modal_joint_formula_inference import JointInferenceSession
        package._require(type(runtime) is package.Runtime, "verified Legal package runtime required")
        self._original = runtime
        self._session = (JointInferenceSession(runtime.model)
                         if runtime._payload["formula_checkpoint"] is not None else None)

    def _check(self):
        package._require(_source_sha256() == _SOURCE_AT_IMPORT, "optimized Legal runtime source changed since import")
        package._require(self._original._payload["producer"] == package._producer(),
                         "Legal inference producer changed")

    def _inference_implementation(self):
        from ....optimizers.logic_theorem_optimizer import modal_joint_formula_inference as projection
        from ....optimizers.logic_theorem_optimizer.modal_latent_formula_inference import inference_implementation
        from ....optimizers.logic_theorem_optimizer.legal_modal_parser_inference import inference_implementation as parser_implementation
        return {
            "schema": "legal-optimized-inference/v1", "source_sha256": _SOURCE_AT_IMPORT,
            "projection_source_sha256": projection.inference_implementation()["source_sha256"],
            "formula_decoder": inference_implementation(), "parser": parser_implementation(),
            "checkpoint_conversion_performed": False}

    def describe(self):
        self._check()
        return {**self._original.describe(), "inference_implementation": self._inference_implementation()}

    @_cpu_inference
    def infer(self, rows):
        from ....optimizers.logic_theorem_optimizer import modal_joint_formula as joint
        from ....optimizers.logic_theorem_optimizer.modal_joint_formula_inference import raw_projection
        self._check()
        runtime = self._original
        package._require(joint._core_binding(runtime.model) == runtime._payload["core_binding"],
                         "Legal core changed after loading")
        samples = _rows(rows, runtime._payload["embedding_contract"])
        if self._session is not None:
            # These samples have just been built by the original row/sample
            # code from bounded source rows. Empty embedding heads contribute
            # exact zeros; their unused feature readouts can be omitted here.
            # Standalone sessions still evaluate custom sample features.
            result = self._session.infer(samples, _validated_package_samples=True)
        else:
            result = {"rows": [{"id": sample.sample_id,
                       "embedding": raw_projection(runtime.model, sample, _validated_package_sample=True),
                       "formal_logic": None, "reason": "learned_formula_head_absent"}
                       for sample in samples]}
        package._require(joint._core_binding(runtime.model) == runtime._payload["core_binding"],
                         "inference mutated Legal core")
        self._check()
        return {"runtime": package.RUNTIME, "checkpoint_sha256": runtime._bundle_sha256,
                "result": result, "training_steps": 0, "provider_calls": 0,
                "inference_implementation": self._inference_implementation(), **package.FALSE}


def optimize_autoencoder(autoencoder):
    """Wrap an already loaded Legal Hub runtime; never load or convert weights."""
    package._require(isinstance(autoencoder, HubAutoencoder) and autoencoder.domain == "legal_ir",
                     "loaded Legal Hub autoencoder required")
    if isinstance(autoencoder.runtime, OptimizedRuntime):
        return autoencoder
    return HubAutoencoder("legal_ir", OptimizedRuntime(autoencoder.runtime),
                          autoencoder.manifest, autoencoder.descriptor)
