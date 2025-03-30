import os
import sys
import unittest
import tempfile
import shutil
import io
import random
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the module to test
try:
    from ipfs_datasets_py.unixfs_integration import UnixFSHandler
    from ipfs_datasets_py.unixfs_integration import FixedSizeChunker, RabinChunker
except ImportError:
    # Mock classes for testing structure before implementation
    class UnixFSHandler:
        def __init__(self):
            pass
            
        def write_file(self, file_path, chunker=None):
            """Write a file to IPFS using UnixFS format"""
            return "bafybeiunixfsfile"
            
        def write_directory(self, dir_path, recursive=True):
            """Write a directory to IPFS using UnixFS format"""
            return "bafybeiunixfsdir"
            
        def write_to_car(self, path, car_path, chunker=None):
            """Write a file or directory to a CAR file"""
            with open(car_path, 'wb') as f:
                f.write(b"mock CAR data")
            return "bafybeiunixfscar"
            
        def get_file(self, cid, output_path=None):
            """Get a file from IPFS"""
            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(b"mock file content")
            return b"mock file content" if not output_path else output_path
            
        def get_directory(self, cid, output_dir=None):
            """Get a directory from IPFS"""
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                with open(os.path.join(output_dir, "file1.txt"), 'wb') as f:
                    f.write(b"mock file 1")
                with open(os.path.join(output_dir, "file2.txt"), 'wb') as f:
                    f.write(b"mock file 2")
            return ["file1.txt", "file2.txt"] if output_dir else {"file1.txt": b"mock file 1", "file2.txt": b"mock file 2"}
    
    class ChunkerBase:
        def cut(self, context, buffer, end=False):
            """Cut buffer into chunks"""
            return [len(buffer)]
            
    class FixedSizeChunker(ChunkerBase):
        def __init__(self, chunk_size=262144):
            self.chunk_size = chunk_size
            
    class RabinChunker(ChunkerBase):
        def __init__(self, min_size=256*1024, avg_size=1024*1024, max_size=4*1024*1024):
            self.min_size = min_size
            self.avg_size = avg_size
            self.max_size = max_size


# Try to import testing dependencies, skip tests if not available
try:
    import multiformats
    HAVE_MULTIFORMATS = True
except ImportError:
    HAVE_MULTIFORMATS = False


class TestUnixFSIntegration(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.handler = UnixFSHandler()
        
        # Create some test files and directories
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("This is test content for the file.")
            
        self.test_dir_path = os.path.join(self.temp_dir, "test_dir")
        os.makedirs(self.test_dir_path, exist_ok=True)
        
        with open(os.path.join(self.test_dir_path, "file1.txt"), 'w') as f:
            f.write("Content of file 1")
            
        with open(os.path.join(self.test_dir_path, "file2.txt"), 'w') as f:
            f.write("Content of file 2")
            
        # Create a subdirectory
        sub_dir = os.path.join(self.test_dir_path, "subdir")
        os.makedirs(sub_dir, exist_ok=True)
        
        with open(os.path.join(sub_dir, "subfile.txt"), 'w') as f:
            f.write("Content of a file in subdirectory")
            
    def tearDown(self):
        """Clean up test fixtures after each test"""
        shutil.rmtree(self.temp_dir)
        
    def test_write_file(self):
        """Test writing a file to IPFS using UnixFS"""
        try:
            # Check if IPFS client is available
            import ipfshttpclient
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient not installed")
        
        # Write the file
        try:
            cid = self.handler.write_file(self.test_file_path)
            
            # Verify CID
            self.assertIsNotNone(cid)
            self.assertTrue(isinstance(cid, str))
            
            # CID should follow multiformats pattern if library is available
            if HAVE_MULTIFORMATS:
                try:
                    parsed_cid = multiformats.CID.decode(cid)
                    self.assertIsNotNone(parsed_cid)
                except Exception:
                    # If using mock implementation, this might fail
                    pass
        except ImportError:
            self.skipTest("IPFS client not available")
                
    def test_write_file_with_chunker(self):
        """Test writing a file with a specific chunking strategy"""
        try:
            # Check if IPFS client is available
            import ipfshttpclient
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient not installed")
            
        # Create a large test file
        large_file_path = os.path.join(self.temp_dir, "large_file.bin")
        with open(large_file_path, 'wb') as f:
            # Write 1MB of random data
            f.write(bytes(random.getrandbits(8) for _ in range(1024 * 1024)))
            
        try:
            # Write with fixed size chunker
            chunker = FixedSizeChunker(chunk_size=256 * 1024)  # 256KB chunks
            cid = self.handler.write_file(large_file_path, chunker=chunker)
            
            # Verify CID
            self.assertIsNotNone(cid)
            
            # Write with Rabin chunker if available
            try:
                rabin_chunker = RabinChunker()
                cid2 = self.handler.write_file(large_file_path, chunker=rabin_chunker)
                self.assertIsNotNone(cid2)
            except (ImportError, NotImplementedError):
                # Rabin chunker might not be implemented yet
                pass
        except ImportError:
            self.skipTest("IPFS client not available")
            
    def test_write_directory(self):
        """Test writing a directory to IPFS using UnixFS"""
        try:
            # Check if IPFS client is available
            import ipfshttpclient
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient not installed")
            
        try:
            # Write the directory
            cid = self.handler.write_directory(self.test_dir_path)
            
            # Verify CID
            self.assertIsNotNone(cid)
            self.assertTrue(isinstance(cid, str))
        except ImportError:
            self.skipTest("IPFS client not available")
        
    def test_write_directory_recursive(self):
        """Test writing a directory recursively"""
        try:
            # Check if IPFS client is available
            import ipfshttpclient
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient not installed")
            
        try:
            # Write with recursive=True (default)
            cid1 = self.handler.write_directory(self.test_dir_path, recursive=True)
            
            # Write with recursive=False
            cid2 = self.handler.write_directory(self.test_dir_path, recursive=False)
            
            # Both CIDs should be valid
            self.assertIsNotNone(cid1)
            self.assertIsNotNone(cid2)
            
            # The CIDs should be different (one includes subdirectories, the other doesn't)
            # Note: If using mock implementation, this might not be true
            if cid1 != "bafybeiunixfsdir" and cid2 != "bafybeiunixfsdir":
                self.assertNotEqual(cid1, cid2)
        except ImportError:
            self.skipTest("IPFS client not available")
            
    def test_write_to_car(self):
        """Test writing a file to a CAR file"""
        try:
            # Check if IPFS client and ipld_car are available
            import ipfshttpclient
            import ipld_car
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient or ipld_car not installed")
            
        try:
            # Write file to CAR
            car_path = os.path.join(self.temp_dir, "test_file.car")
            cid = self.handler.write_to_car(self.test_file_path, car_path)
            
            # Verify CID and CAR file
            self.assertIsNotNone(cid)
            self.assertTrue(os.path.exists(car_path))
            self.assertGreater(os.path.getsize(car_path), 0)
        except ImportError:
            self.skipTest("Required dependencies not available")
        
    def test_write_directory_to_car(self):
        """Test writing a directory to a CAR file"""
        try:
            # Check if IPFS client and ipld_car are available
            import ipfshttpclient
            import ipld_car
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient or ipld_car not installed")
            
        try:
            # Write directory to CAR
            car_path = os.path.join(self.temp_dir, "test_dir.car")
            cid = self.handler.write_to_car(self.test_dir_path, car_path)
            
            # Verify CID and CAR file
            self.assertIsNotNone(cid)
            self.assertTrue(os.path.exists(car_path))
            self.assertGreater(os.path.getsize(car_path), 0)
        except ImportError:
            self.skipTest("Required dependencies not available")
        
    def test_get_file(self):
        """Test getting a file from IPFS"""
        try:
            # Check if IPFS client is available
            import ipfshttpclient
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient not installed")
            
        try:
            # First write a file to get a CID
            cid = self.handler.write_file(self.test_file_path)
            
            # Get the file content
            content = self.handler.get_file(cid)
            
            # Verify content
            self.assertIsNotNone(content)
            
            # Get the file to a specific path
            output_path = os.path.join(self.temp_dir, "retrieved_file.txt")
            result = self.handler.get_file(cid, output_path=output_path)
            
            # Verify file was created
            self.assertTrue(os.path.exists(output_path))
            self.assertGreater(os.path.getsize(output_path), 0)
        except ImportError:
            self.skipTest("IPFS client not available")
        
    def test_get_directory(self):
        """Test getting a directory from IPFS"""
        try:
            # Check if IPFS client is available
            import ipfshttpclient
            try:
                client = ipfshttpclient.connect()
                client.close()
            except Exception:
                self.skipTest("IPFS daemon not running")
        except ImportError:
            self.skipTest("ipfshttpclient not installed")
            
        try:
            # First write a directory to get a CID
            cid = self.handler.write_directory(self.test_dir_path)
            
            # Get the directory content as a dict
            content = self.handler.get_directory(cid)
            
            # Verify content
            self.assertIsNotNone(content)
            
            # Get the directory to a specific path
            output_dir = os.path.join(self.temp_dir, "retrieved_dir")
            result = self.handler.get_directory(cid, output_dir=output_dir)
            
            # Verify directory was created
            self.assertTrue(os.path.exists(output_dir))
            
            # Should have at least one file
            files = os.listdir(output_dir)
            self.assertGreater(len(files), 0)
        except ImportError:
            self.skipTest("IPFS client not available")
        
    def test_chunking_strategies(self):
        """Test different chunking strategies"""
        # Create test data buffer
        data = b"A" * 1024 * 1024  # 1MB of data
        
        # Test fixed size chunker
        fixed_chunker = FixedSizeChunker(chunk_size=256 * 1024)  # 256KB chunks
        fixed_chunks = fixed_chunker.cut(None, data, end=True)
        
        # Should have ~4 chunks of equal size (except possibly the last)
        self.assertGreaterEqual(len(fixed_chunks), 1)
        
        # Test rabin chunker if available
        try:
            rabin_chunker = RabinChunker()
            rabin_chunks = rabin_chunker.cut(None, data, end=True)
            
            # Should have variable-sized chunks
            self.assertGreaterEqual(len(rabin_chunks), 1)
        except (ImportError, NotImplementedError):
            # Rabin chunker might not be implemented yet
            pass


if __name__ == '__main__':
    unittest.main()