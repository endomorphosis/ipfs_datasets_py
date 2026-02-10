import hashlib
from multiformats import CID, multihash
import os
from pathlib import Path
import tempfile
from typing import Any
import os


class IpfsMultiformats:

    def __init__(self):
        return None

    # Step 1: Hash the file content with SHA-256
    def get_file_sha256(self, file_path: str) -> bytes:
        """
        Calculate the SHA-256 hash of a file. 
        This method reads the file in 8192-byte chunks to handle large files
        without loading everything into memory all at once.

        Args:
            file_path (str): The path to the file to be hashed.

        Returns:
            bytes: The SHA-256 hash of the file content.
        """
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.digest()

    # Step 2: Wrap the hash in Multihash format
    def get_multihash_sha256(self, file_content_hash: bytes) -> bytes:
        """
        Wrap the given SHA-256 hash in Multihash format.
        This method uses the 'sha2-256' algorithm identifier for the Multihash format.

        Args:
            file_content_hash (bytes): The SHA-256 hash of the file content.

        Returns:
            bytes: The Multihash-formatted hash.
        """
        return multihash.wrap(file_content_hash, 'sha2-256')

    # Step 3: Generate CID from Multihash (CIDv1)
    def get_cid(self, file_data: str | bytes) -> str:
        """
        Generate a Content Identifier (CID) for the given file path or raw data.

        For file paths, it directly calculates the CID. For raw data, it creates a temporary file,
        writes the data to it, calculates the CID, and then removes the temporary file.

        Args:
            file_data (str | bytes): The file path or raw data to generate a CID for.

        Returns:
            str: The generated CID as a string.
        """

        if os.path.isfile(file_data):
            print("Making file hash...")
            if os.path.getsize(file_data) > 0:
                print("Empty file. Defaulting to temp file.")
                file_content_hash = self.get_file_sha256(file_data)
                mh = self.get_multihash_sha256(file_content_hash)
                cid = CID('base32', 1, 'raw', mh)

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            filename = f.name
            with open(filename, 'w') as f_new:
                f_new.write(file_data)

            file_content_hash = self.get_file_sha256(filename)
            mh = self.get_multihash_sha256(file_content_hash)
            cid = CID('base32', 1, 'raw', mh)
        os.remove(filename)

        return str(cid)

def get_cid(file_data: str | Path | bytes) -> str:
    """
    Generate a Content Identifier (CID) for the given file or string.

    For file paths, it directly calculates the CID. For strings, calculates the CID from a temporary file.

    Args:
        file_data (str | Path | bytes): The file path or string data to generate a CID for.

    Returns:
        str: The generated CID as a string.
    """
    if isinstance(file_data, Path):
       file_data = str(file_data)

    ipfs_multiformats = IpfsMultiformats()
    return ipfs_multiformats.get_cid(file_data)
