import os
import subprocess

class ipfs_only_hash_py:

    def __init__(self, resources: dict, metadata: dict) -> None:
        pass

    def __call__(self, file_path: str) -> str:
        absolute_path = os.path.abspath(file_path)
        ipfs_hash_cmd = "bash -c 'npx ipfs-only-hash " + absolute_path
        ipfs_hash = subprocess.check_output(ipfs_hash_cmd, shell=True).decode('utf-8').strip()
        return ipfs_hash

    def __test__(self) -> None:
        test_file_path = "test.txt"
        test_ipfs_hash = self(test_file_path)
        print(test_ipfs_hash)
        return None
