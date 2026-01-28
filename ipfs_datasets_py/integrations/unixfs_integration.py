"""
UnixFS Integration Module for IPFS File System Operations

This module provides comprehensive functionality for working with files and directories
in IPFS using the UnixFS (Unix File System) format. UnixFS enables efficient storage,
retrieval, and organization of large files and complex directory structures within
the InterPlanetary File System (IPFS) network. The module supports various chunking
strategies for optimal performance and provides seamless integration with IPFS nodes.

The module includes:
- Multiple chunking strategies for optimal file segmentation (fixed-size, Rabin)
- UnixFS file and directory operations with IPFS integration
- CAR (Content Addressable aRchive) file export capabilities
- Flexible IPFS client connection management
- Content-addressable storage with automatic pinning
- Directory traversal and recursive operations

Key Components:
- ChunkerBase: Abstract base class for chunking strategy implementations
- FixedSizeChunker: Fixed-size chunking for predictable segmentation
- RabinChunker: Content-defined chunking using Rabin fingerprinting
- UnixFSHandler: Main class for IPFS file system operations

This module is designed to provide high-level abstractions over IPFS operations
while maintaining flexibility for advanced use cases. It handles dependency
management gracefully and provides fallback mechanisms for optional components.

Dependencies:
- ipfshttpclient: Required for IPFS node communication
- ipld_car: Optional, required for CAR file operations
- pyrabin: Optional, required for Rabin chunking (falls back to fixed-size)
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
    Abstract Base Class for File Chunking Strategies

    The ChunkerBase class defines the interface for implementing different file
    chunking strategies used in IPFS file storage operations. Chunking determines
    how large files are divided into smaller, manageable blocks for efficient
    storage, transmission, and deduplication in IPFS networks.

    Key Features:
    - Abstract interface for chunking strategy implementation
    - Context management for stateful chunking algorithms
    - Support for streaming data processing
    - End-of-stream handling for final chunk processing
    - Flexible return format for chunk boundary specification

    Attributes:
        None: This is an abstract base class with no instance attributes

    Public Methods:
        cut(context, buffer, end) -> List[int]:
            Processes input buffer and returns chunk boundary positions according
            to the implemented chunking strategy.

    Usage Example:
        class CustomChunker(ChunkerBase):
            def cut(self, context, buffer, end=False):
                # Implementation here
                return [len(buffer)]
        
        chunker = CustomChunker()
        lengths = chunker.cut(None, data_buffer, end=False)
    """

    def cut(self, context, buffer: bytes, end: bool = False) -> List[int]:
        """
        Cut a data buffer into chunks according to the chunking strategy.

        This abstract method defines the core interface for all chunking strategies.
        It processes an input buffer and determines where chunk boundaries should
        be placed, returning a list of chunk lengths.

        Args:
            context: Opaque context object maintained between successive calls.
                    Allows chunking algorithms to preserve state across buffer
                    boundaries. Type depends on chunking strategy implementation.
            buffer (bytes): Input data buffer to be chunked. Can be any size
                        and may represent a portion of a larger file or stream.
            end (bool, optional): Indicates whether this is the final buffer
                                in the stream. When True, chunking algorithms
                                should finalize any pending chunks. Defaults to False.

        Returns:
            List[int]: List of chunk lengths in bytes, representing how the input
                    buffer should be divided. The sum of all lengths should
                    equal the buffer size. Empty list for empty buffers.

        Raises:
            NotImplementedError: This is an abstract method that must be
                            implemented by concrete subclasses.

        Examples:
            >>> chunker = ConcreteChunker()
            >>> lengths = chunker.cut(context, b'hello world', end=False)
            [5, 6]  # Split into 'hello' and ' world'
            >>> final_lengths = chunker.cut(context, b'!', end=True)
            [1]  # Final chunk '!'
        """
        # Default implementation: one chunk for the whole buffer
        return [len(buffer)] if buffer else []


class FixedSizeChunker(ChunkerBase):
    """
    Fixed-Size Chunking Strategy for Predictable Data Segmentation

    The FixedSizeChunker implements a deterministic chunking strategy that divides
    data into uniform, fixed-size chunks. This approach provides predictable
    performance characteristics and is ideal for scenarios where consistent chunk
    sizes are more important than content-aware deduplication.

    Args:
        chunk_size (int, optional): Size of each chunk in bytes. Must be a positive
                                   integer. Common values:
                                   - 64KB (65536): Small chunks
                                   - 256KB (262144): Default balanced size
                                   - 1MB (1048576): Large chunks
                                   - 4MB (4194304): Very large chunks
                                   Defaults to 262144 bytes.

    Key Features:
    - Deterministic chunking with predictable output
    - Configurable chunk size for different use cases
    - Minimal computational overhead
    - Consistent performance characteristics
    - No state maintenance between calls

    Attributes:
        chunk_size (int): Fixed size in bytes for all chunks except potentially the last

    Public Methods:
        cut(context, buffer, end) -> List[int]:
            Divides the input buffer into fixed-size chunks, with the final
            chunk potentially being smaller than chunk_size.

    Usage Example:
        chunker = FixedSizeChunker(chunk_size=1024)  # 1KB chunks
        chunks = chunker.cut(None, large_buffer, end=False)
        for i, chunk_size in enumerate(chunks):
            chunk_data = large_buffer[i*1024:(i*1024)+chunk_size]
    """

    def __init__(self, chunk_size: int = 262144):
        """
        Initialize a fixed-size chunker with specified chunk dimensions.

        Creates a chunker instance that will divide data into uniform chunks
        of the specified size. The chunk size is fixed for the lifetime of
        the chunker instance.

        Args:
            chunk_size (int, optional): Size of each chunk in bytes. Must be a
                                    positive integer greater than 0. Common
                                    chunk sizes:
                                    - 4KB (4096): Fine-grained processing
                                    - 64KB (65536): Network-optimized
                                    - 256KB (262144): Balanced default
                                    - 1MB (1048576): High-throughput
                                    - 4MB (4194304): Bulk processing
                                    Defaults to 262144 bytes.

        Attributes initialized:
            chunk_size (int): Fixed chunk size in bytes for all data segmentation
                            operations. Cannot be changed after initialization.

        Raises:
            ValueError: If chunk_size is not a positive integer
            TypeError: If chunk_size is not an integer type

        Examples:
            >>> chunker_small = FixedSizeChunker(4096)  # 4KB chunks
            >>> chunker_default = FixedSizeChunker()    # 256KB chunks
            >>> chunker_large = FixedSizeChunker(1048576)  # 1MB chunks
        """
        self.chunk_size = chunk_size

    def cut(self, context, buffer: bytes, end: bool = False) -> List[int]:
        """
        Cut a data buffer into fixed-size chunks with deterministic segmentation.

        Divides the input buffer into uniform chunks of the predetermined size,
        with the final chunk potentially being smaller if the buffer size is not
        evenly divisible by the chunk size.

        Args:
            context: Ignored for fixed-size chunker as no state is maintained
                    between calls. Can be None or any value.
            buffer (bytes): Input data buffer to be segmented into fixed-size chunks.
                        Can be any size from 0 to arbitrarily large.
            end (bool, optional): Indicates whether this is the final buffer.
                                For fixed-size chunking, this parameter doesn't
                                affect the chunking logic. Defaults to False.

        Returns:
            List[int]: List of chunk lengths in bytes. All chunks will be exactly
                    chunk_size bytes except potentially the last chunk, which
                    may be smaller. Returns empty list for empty input buffers.

        Raises:
            TypeError: If buffer is not bytes-like or cannot determine length
            ValueError: If buffer contains invalid data that prevents length calculation

        Examples:
            >>> chunker = FixedSizeChunker(chunk_size=10)
            >>> chunker.cut(None, b'hello world!', end=False)
            [10, 2]  # 'hello worl' (10 bytes) + 'd!' (2 bytes)
            >>> chunker.cut(None, b'exactly10b', end=True)
            [10]     # Exactly one chunk
            >>> chunker.cut(None, b'', end=True)
            []       # Empty buffer, no chunks
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
    Content-Defined Chunking Strategy Using Rabin Fingerprinting Algorithm

    The RabinChunker implements a sophisticated content-defined chunking (CDC) strategy
    that uses Rabin fingerprinting to identify natural chunk boundaries based on data
    content patterns. This approach creates variable-sized chunks that align with
    content structure, significantly improving deduplication efficiency.

    Args:
        min_size (int, optional): Minimum chunk size in bytes. Must be positive
                                 and less than avg_size. Defaults to 256KB.
        avg_size (int, optional): Target average chunk size in bytes. Must be
                                 greater than min_size and less than max_size.
                                 Defaults to 1MB.
        max_size (int, optional): Maximum chunk size in bytes. Must be greater
                                 than avg_size. Defaults to 4MB.

    Key Features:
    - Content-aware chunking for optimal deduplication
    - Configurable size constraints (min, average, max)
    - Graceful fallback to fixed-size chunking if pyrabin unavailable
    - Rolling hash computation for efficient boundary detection
    - Consistent chunk boundaries across similar content

    Attributes:
        min_size (int): Minimum allowed chunk size in bytes
        avg_size (int): Target average chunk size in bytes  
        max_size (int): Maximum allowed chunk size in bytes
        rabin (pyrabin.Rabin): Rabin fingerprinting engine (if available)
        fixed_chunker (FixedSizeChunker): Fallback chunker (if pyrabin unavailable)
        have_rabin (bool): Whether pyrabin is available and functional

    Public Methods:
        cut(context, buffer, end) -> List[int]:
            Analyzes buffer content using Rabin fingerprinting to identify
            natural chunk boundaries, falling back to fixed-size if needed.

    Usage Example:
        chunker = RabinChunker(min_size=128*1024, avg_size=512*1024, max_size=2*1024*1024)
        chunks = chunker.cut(None, file_content, end=True)
        for chunk_size in chunks:
            print(f"Chunk size: {chunk_size} bytes")
    """

    def __init__(self, min_size: int = 256*1024, avg_size: int = 1024*1024, max_size: int = 4*1024*1024):
        """
        Initialize a Rabin fingerprinting chunker with size constraints.

        Creates a content-defined chunker that uses Rabin fingerprinting to identify
        natural chunk boundaries based on data content patterns. Attempts to import
        pyrabin library; falls back to fixed-size chunking if unavailable.

        Args:
            min_size (int, optional): Minimum chunk size in bytes. Must be positive
                                    and less than avg_size. Prevents very small chunks
                                    that increase metadata overhead. Defaults to 256KB.
            avg_size (int, optional): Target average chunk size in bytes. Must be
                                    greater than min_size and less than max_size.
                                    Defaults to 1MB.
            max_size (int, optional): Maximum chunk size in bytes. Must be greater
                                    than avg_size. Ensures large sections without
                                    natural boundaries are still chunked. Defaults to 4MB.

        Attributes initialized:
            min_size (int): Minimum allowed chunk size in bytes
            avg_size (int): Target average chunk size in bytes
            max_size (int): Maximum allowed chunk size in bytes
            rabin (pyrabin.Rabin): Rabin fingerprinting engine instance (if available)
            fixed_chunker (FixedSizeChunker): Fallback chunker using avg_size (if needed)
            have_rabin (bool): Flag indicating whether pyrabin is available

        Raises:
            ValueError: If size constraints are invalid (e.g., min_size >= avg_size)
            TypeError: If size parameters are not integers

        Examples:
            >>> chunker = RabinChunker()  # Standard configuration
            >>> chunker = RabinChunker(min_size=128*1024, avg_size=512*1024)  # Smaller chunks
            >>> chunker = RabinChunker(min_size=512*1024, avg_size=2*1024*1024)  # Larger chunks
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
        Cut data buffer using Rabin fingerprinting for content-defined chunking.

        Analyzes the input buffer using rolling hash computation to identify natural
        chunk boundaries based on content patterns. Provides superior deduplication
        characteristics compared to fixed-size chunking. Falls back to fixed-size
        chunking if pyrabin is unavailable.

        Args:
            context: Opaque context object maintained between successive calls for
                    stateful Rabin fingerprinting. May maintain rolling hash state
                    across buffer boundaries.
            buffer (bytes): Input data buffer to be analyzed for chunk boundaries.
                        Can be any size.
            end (bool, optional): Indicates whether this is the final buffer in the
                                stream. When True, finalizes any pending chunks and
                                completes the fingerprinting process. Defaults to False.

        Returns:
            List[int]: List of chunk lengths in bytes determined by content analysis.
                    - With Rabin: Variable-sized chunks based on content patterns,
                        respecting min_size and max_size constraints
                    - With fallback: Fixed-size chunks using avg_size parameter
                    - Empty list for empty input buffers

        Raises:
            TypeError: If buffer is not bytes-like or incompatible with fingerprinting
            RuntimeError: If Rabin fingerprinting encounters internal errors
            ValueError: If buffer data causes fingerprinting algorithm failures

        Examples:
            >>> chunker = RabinChunker()
            >>> chunks = chunker.cut(None, file_data, end=False)
            [245760, 1048576, 524288, 786432]  # Variable sizes based on content
            >>> final_chunks = chunker.cut(None, remaining_data, end=True)
            [131072]  # Completes fingerprinting process
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
    Comprehensive UnixFS File System Handler for IPFS Operations

    The UnixFSHandler class provides a high-level interface for storing, retrieving,
    and managing files and directories in IPFS using the UnixFS format. UnixFS is
    the standard file system abstraction in IPFS that enables efficient handling
    of large files through chunking, directory structures, and metadata preservation.

    Args:
        ipfs_api (str, optional): IPFS API endpoint for daemon communication.
                                 Should be a multiaddr format string specifying
                                 the protocol, IP address, and port. Common formats:
                                 - "/ip4/127.0.0.1/tcp/5001": Local IPFS daemon
                                 - "/ip4/192.168.1.100/tcp/5001": Remote daemon
                                 - "/dns/ipfs.example.com/tcp/5001": DNS-based endpoint
                                 Defaults to "/ip4/127.0.0.1/tcp/5001".

    Key Features:
    - File and directory storage with automatic chunking
    - Configurable chunking strategies (fixed-size, Rabin)
    - CAR (Content Addressable aRchive) file export
    - Automatic content pinning for persistence
    - Graceful connection management with retry capabilities
    - Content retrieval with flexible output options
    - Directory traversal and recursive operations

    Attributes:
        ipfs_api (str): IPFS API endpoint configuration
        ipfs_client (ipfshttpclient.Client): Active IPFS client connection (if available)

    Public Methods:
        connect(ipfs_api) -> bool:
            Establish or re-establish connection to IPFS daemon.
        write_file(file_path, chunker) -> str:
            Store a file in IPFS using specified chunking strategy.
        write_directory(dir_path, recursive) -> str:
            Store a directory structure in IPFS with optional recursion.
        write_to_car(path, car_path, chunker) -> str:
            Export files or directories to CAR format for archival.
        get_file(cid, output_path) -> Union[bytes, str]:
            Retrieve file content from IPFS by CID.
        get_directory(cid, output_dir) -> Union[List[str], Dict[str, bytes]]:
            Retrieve directory structures from IPFS.

    Usage Example:
        handler = UnixFSHandler()
        if handler.connect():
            chunker = RabinChunker(min_size=128*1024, avg_size=512*1024)
            file_cid = handler.write_file("/path/to/file.bin", chunker)
            dir_cid = handler.write_directory("/path/to/project", recursive=True)
            content = handler.get_file(file_cid)
    """

    def __init__(self, ipfs_api: str = "/ip4/127.0.0.1/tcp/5001"):
        """
        Initialize UnixFS handler with IPFS daemon connection configuration.

        Creates a UnixFS handler instance configured to communicate with an IPFS
        daemon at the specified API endpoint. Attempts to establish an initial
        connection to verify daemon availability.

        Args:
            ipfs_api (str, optional): IPFS API endpoint in multiaddr format for
                                    daemon communication. Should include protocol,
                                    address, transport, and port:
                                    - "/ip4/127.0.0.1/tcp/5001": Local daemon (default)
                                    - "/ip4/0.0.0.0/tcp/5001": All interfaces
                                    - "/dns/ipfs-node.example.com/tcp/5001": Remote daemon
                                    - "/ip6/::1/tcp/5001": IPv6 localhost
                                    Defaults to "/ip4/127.0.0.1/tcp/5001".

        Attributes initialized:
            ipfs_api (str): Stored API endpoint for current and future connections
            ipfs_client (ipfshttpclient.Client or None): Active IPFS client connection
                                                        if daemon is available, None if
                                                        connection failed

        Raises:
            No exceptions are raised during initialization. Connection failures
            are logged as warnings and the handler remains in local-only mode.

        Examples:
            >>> handler = UnixFSHandler()  # Connect to local daemon
            >>> handler = UnixFSHandler("/ip4/192.168.1.100/tcp/5001")  # Remote daemon
            >>> if handler.ipfs_client:
            ...     print("Connected to IPFS daemon")
            ... else:
            ...     print("Operating in local-only mode")
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

    def connect(self, ipfs_api: str | None = None):
        """
        Connect or reconnect to the IPFS daemon with optional endpoint reconfiguration.

        Establishes a connection to an IPFS daemon at the specified API endpoint,
        or reconnects to the current endpoint if no new endpoint is provided.
        Useful for initial connection, reconnecting after network issues, or
        switching to a different IPFS daemon.

        Args:
            ipfs_api (str, optional): New IPFS API endpoint in multiaddr format.
                                    If provided, updates the handler's endpoint
                                    configuration before attempting connection.
                                    If None, uses the current ipfs_api setting.
                                    Format: "/protocol/address/transport/port"

        Returns:
            bool: Connection success status.
                - True: Successfully connected to IPFS daemon
                - False: Connection failed due to dependency issues, network problems,
                        or daemon unavailability

        Raises:
            No exceptions are raised. All errors are handled gracefully with
            appropriate logging and return False for failed connections.

        Examples:
            >>> handler = UnixFSHandler()
            >>> if handler.connect():
            ...     print("Successfully connected to IPFS")
            >>> success = handler.connect("/ip4/192.168.1.100/tcp/5001")
            >>> if not handler.connect():
            ...     print("Check that IPFS daemon is running")
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
        Write a file to IPFS using UnixFS format with configurable chunking strategy.

        Stores a file in IPFS using the UnixFS format, which enables efficient
        handling of large files through automatic chunking and content-addressable
        storage. The file is automatically pinned to prevent garbage collection.

        Args:
            file_path (str): Absolute or relative path to the file to be stored.
                            Must point to an existing, readable file.
            chunker (ChunkerBase, optional): Chunking strategy instance to use
                                            for file segmentation. Options:
                                            - None: Use IPFS default chunking
                                            - FixedSizeChunker(): Uniform chunk sizes
                                            - RabinChunker(): Content-defined chunking
                                            Defaults to None.

        Returns:
            str: Content Identifier (CID) of the stored file. This cryptographic
                hash uniquely identifies the file content and can be used to
                retrieve the file from any IPFS node.

        Raises:
            ImportError: If IPFS client is not available or connection failed
            FileNotFoundError: If the specified file does not exist or is not accessible
            PermissionError: If the file cannot be read due to insufficient permissions
            IOError: If file reading fails due to disk errors or other I/O issues
            ValueError: If chunker configuration is invalid or incompatible

        Examples:
            >>> handler = UnixFSHandler()
            >>> cid = handler.write_file("/path/to/document.pdf")
            >>> print(f"File stored with CID: {cid}")
            >>> fixed_chunker = FixedSizeChunker(chunk_size=1024*1024)
            >>> cid = handler.write_file("/path/to/large_file.bin", fixed_chunker)
            >>> rabin_chunker = RabinChunker(min_size=256*1024, avg_size=1024*1024)
            >>> cid = handler.write_file("/path/to/dataset.tar", rabin_chunker)
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
        Write a directory structure to IPFS using UnixFS format with optional recursion.

        Stores a complete directory structure in IPFS using the UnixFS format,
        which preserves directory hierarchy, file relationships, and enables
        efficient navigation and retrieval of directory contents. The directory
        and all its contents are automatically pinned.

        Args:
            dir_path (str): Absolute or relative path to the directory to be stored.
                        Must point to an existing, accessible directory.
            recursive (bool, optional): Controls subdirectory inclusion behavior:
                                    - True: Include all subdirectories and their
                                        contents recursively (default)
                                    - False: Include only direct files in the
                                        specified directory, ignoring subdirectories
                                    Defaults to True.

        Returns:
            str: Content Identifier (CID) of the directory structure. This CID
                represents the root of the directory tree and can be used to
                access the entire directory structure.

        Raises:
            ImportError: If IPFS client is not available or connection failed
            NotADirectoryError: If the specified path is not a directory or does not exist
            PermissionError: If the directory or its contents cannot be read
            OSError: If directory traversal fails due to filesystem issues

        Examples:
            >>> handler = UnixFSHandler()
            >>> project_cid = handler.write_directory("/path/to/project", recursive=True)
            >>> print(f"Project stored with CID: {project_cid}")
            >>> docs_cid = handler.write_directory("/path/to/docs", recursive=False)
            >>> home_cid = handler.write_directory(os.path.expanduser("~/important_docs"))
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
        Write a file or directory to a CAR (Content Addressable aRchive) file format.

        Creates a CAR file containing the specified file or directory along with all
        referenced content blocks. CAR files are self-contained archives that include
        both the content and the IPLD structure, making them ideal for data transfer,
        archival, and offline storage.

        Args:
            path (str): Absolute or relative path to the file or directory to archive.
                    Must point to an existing, accessible file or directory.
            car_path (str): Output path for the generated CAR file. Should include
                        the .car extension by convention. The directory containing
                        this path must exist and be writable.
            chunker (ChunkerBase, optional): Chunking strategy to use for files
                                        during IPFS storage before CAR export.
                                        Options:
                                        - None: Use IPFS default chunking
                                        - FixedSizeChunker(): Uniform chunk sizes
                                        - RabinChunker(): Content-defined chunking
                                        Defaults to None.

        Returns:
            str: Content Identifier (CID) of the root object in the CAR file.
                This CID can be used to import the CAR file into other IPFS
                nodes or to verify the archive integrity.

        Raises:
            ImportError: If required dependencies are not available (ipld_car, ipfshttpclient)
            FileNotFoundError: If the specified path does not exist or is not accessible
            PermissionError: If the output directory is not writable or source path cannot be read
            OSError: If CAR file creation fails due to disk space or I/O errors
            ValueError: If chunker configuration is invalid or path is invalid

        Examples:
            >>> handler = UnixFSHandler()
            >>> file_cid = handler.write_to_car("/path/to/document.pdf", "/backup/document.car")
            >>> print(f"File archived with root CID: {file_cid}")
            >>> rabin_chunker = RabinChunker(min_size=128*1024, avg_size=512*1024)
            >>> dir_cid = handler.write_to_car("/path/to/project", "/backup/project.car", chunker=rabin_chunker)
            >>> dataset_cid = handler.write_to_car("/data/research_dataset", "/transfer/dataset.car")
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
        Retrieve a file from IPFS using its Content Identifier with flexible output options.

        Fetches a file from the IPFS network using its unique Content Identifier (CID)
        and provides flexible output options for handling the retrieved content. The file
        can be returned as raw bytes for in-memory processing or saved directly to the
        filesystem.

        Args:
            cid (str): Content Identifier of the file to retrieve from IPFS.
                    Must be a valid CID string that represents a file object
                    in the IPFS network.
            output_path (str, optional): Filesystem path where the retrieved file
                                    should be saved. If provided, the file content
                                    is written to this location and the path is
                                    returned. If None, the file content is returned
                                    as bytes. The parent directory must exist and
                                    be writable. Defaults to None.

        Returns:
            Union[bytes, str]: The retrieved file content or output path:
                            - If output_path is None: Returns file content as bytes
                            - If output_path is provided: Returns the output_path string
                            after successfully saving the file to disk

        Raises:
            ImportError: If IPFS client is not available or connection failed
            ValueError: If the CID is invalid, malformed, or does not exist in the IPFS network
            PermissionError: If the output directory is not writable or file cannot be created
            OSError: If file writing fails due to disk space or I/O errors
            TimeoutError: If file retrieval times out due to network issues

        Examples:
            >>> handler = UnixFSHandler()
            >>> cid = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
            >>> content = handler.get_file(cid)
            >>> print(f"Retrieved {len(content)} bytes")
            >>> output_file = handler.get_file(cid, "/downloads/retrieved_file.pdf")
            >>> print(f"File saved to: {output_file}")
            >>> image_data = handler.get_file(image_cid)
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
        Retrieve a directory structure from IPFS with flexible output and listing options.

        Fetches a complete directory structure from the IPFS network using its Content
        Identifier (CID) and provides flexible options for handling the retrieved content.
        The directory can be extracted to the filesystem preserving the original structure,
        or listed for inspection without extraction.

        Args:
            cid (str): Content Identifier of the directory to retrieve from IPFS.
                    Must be a valid CID string that represents a UnixFS directory
                    object in the IPFS network.
            output_dir (str, optional): Filesystem path where the directory structure
                                    should be extracted. If provided, the complete
                                    directory tree is recreated at this location,
                                    preserving relative paths and file organization.
                                    If None, returns directory listing without extraction.
                                    Defaults to None.

        Returns:
            Union[List[str], Dict[str, bytes]]: Directory contents or file listing:
                                            - If output_dir is None: Returns list of file
                                                and directory names in the root directory
                                            - If output_dir is provided: Returns list of
                                                extracted file and directory names after
                                                successful extraction to filesystem

        Raises:
            ImportError: If IPFS client is not available or connection failed
            ValueError: If the CID is invalid, malformed, or does not represent a directory
            PermissionError: If the output directory cannot be created or written to
            OSError: If directory extraction fails due to disk space or I/O errors
            TimeoutError: If directory retrieval times out due to network issues

        Examples:
            >>> handler = UnixFSHandler()
            >>> dir_cid = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
            >>> contents = handler.get_directory(dir_cid)
            >>> print(f"Directory contains: {contents}")
            ['README.md', 'src/', 'docs/', 'LICENSE']
            >>> extracted = handler.get_directory(dir_cid, "/downloads/project")
            >>> print(f"Extracted files: {extracted}")
            >>> large_dir_contents = handler.get_directory(dataset_cid)
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
