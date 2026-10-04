import importlib
import os
import types


def test_embeddings_uses_injected_torch_transformers(monkeypatch):
    # Keep the test hermetic: no heavy imports, no CLI calls.
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_EMBEDDINGS_BACKEND", "hf")

    router_deps = importlib.import_module("ipfs_datasets_py.router_deps")
    embeddings_router = importlib.import_module("ipfs_datasets_py.embeddings_router")
    deps_resolver = importlib.import_module("ipfs_datasets_py.deps_resolver")

    # If the deps injection is working, resolve_module() should never try to
    # import the real heavy modules.
    real_import_module = deps_resolver.importlib.import_module

    def guarded_import(name: str, *args, **kwargs):
        if name in {"torch", "transformers"}:
            raise AssertionError(f"Unexpected import of heavy module: {name}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(deps_resolver.importlib, "import_module", guarded_import)

    # Fake torch module
    torch_mod = types.ModuleType("torch")

    class _NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTensor:
        def __init__(self, data):
            self._data = data

        def to(self, device):
            return self

        def mean(self, dim=1):
            return FakeTensor(self._data)

        def detach(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            # When indexed, _data is a flat list.
            return list(self._data)

        def __getitem__(self, idx):
            return FakeTensor(self._data)

    torch_mod.no_grad = lambda: _NoGrad()
    torch_mod.cuda = _Cuda()

    # Fake transformers module
    transformers_mod = types.ModuleType("transformers")

    class FakeTokenizer:
        def __call__(self, text, padding=True, truncation=True, return_tensors="pt"):
            _ = (text, padding, truncation, return_tensors)
            return {"input_ids": FakeTensor([1, 2, 3])}

    class FakeModel:
        def to(self, device):
            return self

        def eval(self):
            return None

        def __call__(self, **kwargs):
            _ = kwargs

            class _Out:
                # last_hidden_state shape is irrelevant for this test; we only
                # need mean pooling to produce a vector.
                last_hidden_state = FakeTensor([0.25, 0.5, 0.75])

            return _Out()

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(model_name):
            _ = model_name
            return FakeTokenizer()

    class AutoModel:
        @staticmethod
        def from_pretrained(model_name):
            _ = model_name
            return FakeModel()

    transformers_mod.AutoTokenizer = AutoTokenizer
    transformers_mod.AutoModel = AutoModel

    deps = router_deps.RouterDeps()
    deps.set_cached("pip::torch", torch_mod)
    deps.set_cached("pip::transformers", transformers_mod)

    out = embeddings_router.embed_texts(
        ["hello"],
        provider="adapter",
        deps=deps,
        device="cpu",
        model_name="fake/model",
    )

    assert out == [[0.25, 0.5, 0.75]]
