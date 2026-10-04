import os
import subprocess
from typing import Optional


class ipfs_only_hash_py:
    def __init__(self, resources=None, metadata=None, *, npx_path: Optional[str] = None):
        self.resources = resources or {}
        self.metadata = metadata or {}
        self.npx_path = npx_path

    def __call__(self, file_path: str) -> str:
        absolute_path = os.path.abspath(file_path)
        npx = self.npx_path or "npx"
        result = subprocess.check_output([npx, "ipfs-only-hash", absolute_path])
        return result.decode("utf-8").strip()

    def __test__(self):
        test_file_path = "test.txt"
        test_ipfs_hash = self(test_file_path)
        print(test_ipfs_hash)
        return None
