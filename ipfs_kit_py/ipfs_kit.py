# Minimal mock implementation of ipfs_kit for development/testing
# Provides basic methods used across the codebase.

import asyncio
from typing import Any, Dict, List, Optional


class ipfs_kit:
    def __init__(self, resources: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None):
        self.resources = resources or {}
        self.metadata = metadata or {}

    # Embedding-related placeholders used by search_embeddings
    def index_knn(self, *args, **kwargs):
        return None

    def choose_endpoint(self, model: Optional[str] = None):
        return "mock-endpoint"

    # FAISS delegation placeholders expected by search_embeddings
    def start_faiss(self, collection: str, query: str):
        return True

    async def load_faiss(self, dataset: str, knn_index: str):
        return True

    async def ingest_faiss(self, column: str):
        return True

    async def search_faiss(self, collection: str, query_embeddings: Any, n: int = 5):
        # Return mock search results
        return [{"id": i, "score": 1.0 - i * 0.1, "text": f"Result {i}"} for i in range(min(n, 5))]


# Top-level convenience async methods used by IPFS tools
async def get_async(cid: str, output_path: str, timeout: int = 60) -> None:
    await asyncio.sleep(0)  # simulate async
    # Write mock content
    with open(output_path, "wb") as f:
        f.write(f"Mock content for CID {cid}".encode("utf-8"))


def get(cid: str, timeout: int = 60) -> bytes:
    return f"Mock content for CID {cid}".encode("utf-8")


def cat(cid: str, timeout: int = 60) -> bytes:
    return get(cid, timeout)


async def cat_async(cid: str, timeout: int = 60) -> bytes:
    await asyncio.sleep(0)
    return get(cid, timeout)
