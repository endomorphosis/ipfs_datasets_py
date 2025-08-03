"""
UnixFS Integration Module

Provides a class for working with files and directories in IPFS using UnixFS.
This allows for efficient storage and retrieval of large files and directory
structures in IPFS.
"""
import os
from typing import List

# Check for dependencies
try:
    import ipfshttpclient
    HAVE_IPFS = True
except ImportError:
    HAVE_IPFS = False

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False


class ChunkerBase:
    """
    Base class for chunking strategies.
    """

    def cut(self, context, buffer, end=False) -> List[int]:
        """
        Cut a buffer into chunks.

        Args:
            context: Opaque context maintained between calls
            buffer (bytes): Buffer to chunk
            end (bool): Whether this is the last buffer

        Returns:
            List[int]: List of chunk lengths
        """
        # Default implementation: one chunk for the whole buffer
        return [len(buffer)] if buffer else []


class FixedSizeChunker(ChunkerBase):
    """
    Chunker that divides data into fixed-size chunks.
    """

    def __init__(self, chunk_size=262144):
        """
        Initialize a fixed-size chunker.

        Args:
            chunk_size (int): Size of each chunk in bytes, defaults to
                256 KB (262144 bytes).
        """
        self.chunk_size = chunk_size

    def cut(self, context, buffer, end=False) -> List[int]:
        """
        Cut a buffer into fixed-size chunks.

        Args:
            context: Ignored for fixed-size chunker
            buffer (bytes): Buffer to chunk
            end (bool): Whether this is the last buffer

        Returns:
            List[int]: List of chunk lengths
        """
        if not buffer:
            return []

        chunks = []
        remaining = len(buffer)
        pos = 0

        while remaining > 0:
            size = min(remaining, self.chunk_size)
            chunks.append(size)
            pos += size
            remaining -= size

        return chunks


class RabinChunker(ChunkerBase):
    """
    Chunker using Rabin fingerprinting for content-defined chunking.

    Note: This requires the pyrabin package, which is not included by default.
    If the package is not available, this will fall back to fixed-size chunking.
    """

    def __init__(self, min_size=256*1024, avg_size=1024*1024, max_size=4*1024*1024):
        """
        Initialize a Rabin chunker.

        Args:
            min_size (int): Minimum chunk size in bytes
            avg_size (int): Average chunk size in bytes
            max_size (int): Maximum chunk size in bytes
        """
        self.min_size = min_size
        self.avg_size = avg_size
        self.max_size = max_size

        # Try to import pyrabin
        try:
            import pyrabin
            self.rabin = pyrabin.Rabin(min_size, avg_size, max_size)
            self.have_rabin = True
        except ImportError:
            # Fall back to fixed-size chunking
            self.fixed_chunker = FixedSizeChunker(chunk_size=avg_size)
            self.have_rabin = False

    def cut(self, context, buffer, end=False) -> List[int]:
        """
        Cut a buffer using Rabin fingerprinting.

        Args:
            context: Opaque context maintained between calls
            buffer (bytes): Buffer to chunk
            end (bool): Whether this is the last buffer

        Returns:
            List[int]: List of chunk lengths
        """
        if not buffer:
            return []

        if not self.have_rabin:
            # Fall back to fixed-size chunking
            return self.fixed_chunker.cut(context, buffer, end)

        # Use Rabin fingerprinting
        self.rabin.update(buffer)

        # Get the chunk boundaries
        if end:
            chunks = self.rabin.finalize()
        else:
            chunks = self.rabin.fingerprints()

        # Convert to chunk sizes
        sizes = []
        last_pos = 0
        for pos in chunks:
            size = pos - last_pos
            sizes.append(size)
            last_pos = pos

        return sizes


class UnixFSHandler:
    """
    Handles files and directories in IPFS using UnixFS.

    This class provides methods for storing and retrieving files and
    directories in IPFS, using various chunking strategies for efficient
    handling of large files.
    """

    def __init__(self, ipfs_api="/ip4/127.0.0.1/tcp/5001"):
        """
        Initialize a new UnixFSHandler.

        Args:
            ipfs_api (str): IPFS API endpoint, defaults to the local node.
        """
        self.ipfs_api = ipfs_api

        # Connect to IPFS if available
        self.ipfs_client = None
        if HAVE_IPFS:
            try:
                self.ipfs_client = ipfshttpclient.connect(self.ipfs_api)
            except Exception as e:
                print(f"Warning: Could not connect to IPFS at {self.ipfs_api}: {e}")
                print("Operating in local-only mode. Use connect() to retry connection.")

    def connect(self, ipfs_api=None):
        """
        Connect or reconnect to the IPFS daemon.

        Args:
            ipfs_api (str, optional): IPFS API endpoint. If None, use the endpoint
                specified during initialization.

        Returns:
            bool: True if connection successful, False otherwise.
        """
        if ipfs_api:
            self.ipfs_api = ipfs_api

        if not HAVE_IPFS:
            print("Warning: ipfshttpclient not available. Install with pip install ipfshttpclient")
            return False

        try:
            self.ipfs_client = ipfshttpclient.connect(self.ipfs_api)
            return True
        except Exception as e:
            print(f"Error connecting to IPFS at {self.ipfs_api}: {e}")
            return False

    def write_file(self, file_path, chunker=None):
        """
        Write a file to IPFS using UnixFS format.

        Args:
            file_path (str): Path to the file to write
            chunker (ChunkerBase, optional): Chunking strategy to use

        Returns:
            str: CID of the file

        Raises:
            ImportError: If IPFS client is not available
            FileNotFoundError: If the file does not exist
        """
        if not self.ipfs_client:
            raise ImportError("IPFS client is not available")

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Determine chunking strategy
        chunker_str = None
        match chunker:
            case None: # Use default chunking for None
                pass
            case FixedSizeChunker():
                chunker_str = f"size-{chunker.chunk_size}"
            case RabinChunker():
                chunker_str = f"rabin-{chunker.min_size}-{chunker.avg_size}-{chunker.max_size}"

        # Add the file to IPFS
        with open(file_path, 'rb') as f:
            result = self.ipfs_client.add(
                f,
                chunker=chunker_str,
                pin=True
            )

        # Return the CID
        return result['Hash']

    def write_directory(self, dir_path, recursive=True):
        """
        Write a directory to IPFS using UnixFS format.

        Args:
            dir_path (str): Path to the directory to write
            recursive (bool): Whether to include subdirectories

        Returns:
            str: CID of the directory

        Raises:
            ImportError: If IPFS client is not available
            NotADirectoryError: If the path is not a directory
        """
        if not self.ipfs_client:
            raise ImportError("IPFS client is not available")

        if not os.path.isdir(dir_path):
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        # Add the directory to IPFS
        result = self.ipfs_client.add(
            dir_path,
            recursive=recursive,
            pin=True
        )

        # The last item in the result is the directory itself
        return result[-1]['Hash']

    def write_to_car(self, path, car_path, chunker=None):
        """
        Write a file or directory to a CAR file.

        Args:
            path (str): Path to the file or directory to write
            car_path (str): Path for the output CAR file
            chunker (ChunkerBase, optional): Chunking strategy to use for files

        Returns:
            str: CID of the root object in the CAR file

        Raises:
            ImportError: If dependencies are not available
            FileNotFoundError: If the path does not exist
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car is required for CAR export")

        # Add to IPFS first
        if os.path.isfile(path):
            cid = self.write_file(path, chunker=chunker)
        elif os.path.isdir(path):
            cid = self.write_directory(path)
        else:
            raise FileNotFoundError(f"Path not found: {path}")

        # Export from IPFS to CAR
        if not self.ipfs_client:
            raise ImportError("IPFS client is not available")

        # Use 'dag export' to create a CAR file
        with open(car_path, 'wb') as f:
            data = self.ipfs_client.dag.export(cid)
            f.write(data)

        return cid

    def get_file(self, cid, output_path=None):
        """
        Get a file from IPFS.

        Args:
            cid (str): CID of the file to get
            output_path (str, optional): Path to write the file to. If None,
                the file content is returned directly.

        Returns:
            Union[bytes, str]: The file content or the output path

        Raises:
            ImportError: If IPFS client is not available
        """
        if not self.ipfs_client:
            raise ImportError("IPFS client is not available")

        if output_path:
            # Get and save to file
            self.ipfs_client.get(cid, target=os.path.dirname(output_path))

            # IPFS client saves with the CID as the filename, so rename
            cid_path = os.path.join(os.path.dirname(output_path), cid)
            if os.path.exists(cid_path):
                os.rename(cid_path, output_path)

            return output_path
        else:
            # Get and return content
            return self.ipfs_client.cat(cid)

    def get_directory(self, cid, output_dir=None):
        """
        Get a directory from IPFS.

        Args:
            cid (str): CID of the directory to get
            output_dir (str, optional): Directory to write the contents to.
                If None, the directory listing is returned.

        Returns:
            Union[List[str], Dict[str, bytes]]: Directory listing or contents

        Raises:
            ImportError: If IPFS client is not available
        """
        if not self.ipfs_client:
            raise ImportError("IPFS client is not available")

        if output_dir:
            # Create the output directory
            os.makedirs(output_dir, exist_ok=True)

            # Get and extract to directory
            self.ipfs_client.get(cid, target=output_dir)

            # List the files
            cid_dir = os.path.join(output_dir, cid)
            if os.path.exists(cid_dir) and os.path.isdir(cid_dir):
                # Move contents from cid directory to output directory
                for item in os.listdir(cid_dir):
                    src = os.path.join(cid_dir, item)
                    dst = os.path.join(output_dir, item)
                    os.rename(src, dst)

                # Remove the cid directory
                os.rmdir(cid_dir)

            return os.listdir(output_dir)
        else:
            # Get the directory listing
            listing = self.ipfs_client.ls(cid)

            # Return just the names
            if 'Objects' in listing and listing['Objects']:
                objects = listing['Objects'][0]
                if 'Links' in objects:
                    return [link['Name'] for link in objects['Links']]

            return []
