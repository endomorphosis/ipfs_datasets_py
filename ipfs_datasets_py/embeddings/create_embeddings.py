import anyio
import os


from aiohttp import ClientSession
try:
    import datasets  # type: ignore
    from datasets import load_dataset, Dataset  # type: ignore
except ImportError:  # pragma: no cover
    datasets = None  # type: ignore
    load_dataset = None  # type: ignore
    Dataset = object  # type: ignore


def _should_enable_ipfs_kit(resources: dict) -> bool:
    if str(os.getenv("IPFS_KIT_DISABLE", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if str(os.getenv("IPFS_DATASETS_PY_BENCHMARK", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    # Explicit opt-in via resources or env.
    if bool(resources.get("enable_ipfs_kit")):
        return True
    return str(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT", "")).strip().lower() in {"1", "true", "yes", "on"}


def _lazy_load_ipfs_kit():
    try:
        from ipfs_kit_py.ipfs_kit import ipfs_kit
        return ipfs_kit
    except Exception:
        return None

# Try to import accelerate integration for distributed inference
try:
    from ..accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False}


class create_embeddings:
    def __init__(self, resources, metadata):
        self.resources = resources
        self.metadata = metadata
        self.datasets = datasets
        self.index =  {}
        self.cid_list = []
        if len(list(metadata.keys())) > 0:
            for key in metadata.keys():
                setattr(self, key, metadata[key])

        # Initialize ipfs_kit lazily and only when enabled.
        self.ipfs_kit = None
        if _should_enable_ipfs_kit(resources):
            ipfs_kit_factory = _lazy_load_ipfs_kit()
            if ipfs_kit_factory:
                try:
                    self.ipfs_kit = ipfs_kit_factory(resources, metadata)
                except Exception:
                    self.ipfs_kit = None
            
        if "https_endpoints" in resources.keys() and self.ipfs_kit:
            for endpoint in resources["https_endpoints"]:
                self.ipfs_kit.add_https_endpoint(endpoint[0], endpoint[1], endpoint[2])
        self.join_column = None
        self.tokenizer = {}
        
        # Initialize accelerate manager if available and enabled
        self.accelerate_manager = None
        use_accelerate = resources.get("use_accelerate", True)
        if HAVE_ACCELERATE and use_accelerate and is_accelerate_available():
            try:
                self.accelerate_manager = AccelerateManager(
                    resources=resources,
                    enable_distributed=resources.get("enable_distributed", True)
                )
                print("✓ Accelerate integration enabled for distributed inference")
            except Exception as e:
                print(f"⚠ Warning: Failed to initialize accelerate manager: {e}")
                self.accelerate_manager = None
        elif not HAVE_ACCELERATE or not is_accelerate_available():
            print("⚠ Accelerate integration not available, using local inference only")

    def add_https_endpoint(self, model, endpoint, ctx_length):
        if self.ipfs_kit:
            return self.ipfs_kit.add_https_endpoint(model, endpoint, ctx_length)
        else:
            print("Error: ipfs_kit not initialized. Cannot add HTTPS endpoint.")
            return None

    async def index_dataset(self, dataset, split=None, column=None, dst_path=None, models=None):
        """Index a dataset to create embeddings"""
        # Try accelerate first if available
        if self.accelerate_manager:
            try:
                # Use accelerate for distributed inference
                print(f"Using accelerate for distributed embedding generation")
                # Note: This is a placeholder - actual implementation depends on accelerate API
                # For now, fall through to ipfs_kit
            except Exception as e:
                print(f"⚠ Accelerate inference failed, falling back to local: {e}")
        
        # Fallback to ipfs_kit
        if self.ipfs_kit:
            return await self.ipfs_kit.index_dataset(dataset, split, column, dst_path, models)
        else:
            print("Error: Neither accelerate nor ipfs_kit available. Cannot index dataset.")
            return None

    async def create_embeddings(self, dataset, split, column, dst_path, models):
        if self.ipfs_kit:
            await self.ipfs_kit.index_dataset(dataset, split, column, dst_path, models)
            return True
        else:
            print("Error: ipfs_kit not initialized. Cannot create embeddings.")
            return False
           
    async def __call__(self, dataset, split, column, dst_path, models):
        if self.ipfs_kit:
            await self.ipfs_kit.index_dataset(dataset, split, column, dst_path, models)
            return True
        else:
            print("Error: ipfs_kit not initialized. Cannot call create_embeddings.")
            return False

    async def test(self, dataset, split, column, dst_path, models):
        https_endpoints = [
            # ["Alibaba-NLP/gte-large-en-v1.5", "http://127.0.0.1:8080/embed", 8192],
            # ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://127.0.0.1:8082/embed", 32768],
            # # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8080/embed-large", 32000],
            # ["Alibaba-NLP/gte-large-en-v1.5", "http://127.0.0.1:8081/embed", 8192],
            # ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://127.0.0.1:8083/embed", 32768],
            # # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8081/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8080/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8080/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8080/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8081/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8081/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8081/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8082/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8082/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8082/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8083/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8083/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8083/embed-large", 32000],
        ]
        for endpoint in https_endpoints:
            self.add_https_endpoint(endpoint[0], endpoint[1], endpoint[2])
        await self.create_embeddings(dataset, split, column, dst_path, models)
        return True
    
# Alias for compatibility with other modules
CreateEmbeddingsProcessor = create_embeddings

if __name__ == "__main__":
    metadata = {
        "dataset": "TeraflopAI/Caselaw_Access_Project",
        "split": "train",
        "column": "text",
        "models": [
            "Alibaba-NLP/gte-large-en-v1.5",
            "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
            # "dunzhang/stella_en_1.5B-v5",
        ],
        "dst_path": "/storage/teraflopai/tmp"
    }
    resources = {
    }
    create_embeddings_batch = create_embeddings(resources, metadata)
    anyio.run(create_embeddings_batch.test(metadata["dataset"], metadata["split"], metadata["column"], metadata["dst_path"], metadata["models"]))
