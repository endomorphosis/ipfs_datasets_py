
import hashlib
from pathlib import Path

# Calculate MD-5 checksum of a file
def md5_checksum(file_path: Path) -> str:
    hash_list = []
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
