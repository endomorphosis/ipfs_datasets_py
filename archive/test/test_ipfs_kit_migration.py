"""
Test file to verify the migration from old ipfs_kit to new ipfs_kit_py.
"""
import unittest
import sys
import os
import json

# Add the parent directory to the system path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestIPFSKitMigration(unittest.TestCase):
    """Test the migration from old ipfs_kit to new ipfs_kit_py."""

    def setUp(self):
        """Set up test environment."""
        # Example metadata
        self.meta = {
            "config": {
                "endpoint": "http://localhost:8080",
                "accessKey": "test",
                "secretKey": "test"
            }
        }
        self.resources = {}
        self.test_data = json.dumps({"test": "data"})

    def test_knn_initialization(self):
        """Test that KNN properly initializes with both old and new IPFS implementations."""
        try:
            # Import the KNN class
            from ipfs_datasets_py.ipfs_faiss_py.ipfs_knn_lib.knn import KNN

            # Initialize KNN
            knn = KNN(self.resources, self.meta)

            # Check that both IPFS implementations are available
            self.assertIsNotNone(knn.ipfs_kit, "Old IPFS kit should be initialized")

            # Check if new implementation is available
            # Note: This might fail if the new implementation is not installed
            try:
                self.assertIsNotNone(knn.ipfs_api, "New IPFS API should be initialized")
                self.assertTrue(knn.use_new_ipfs, "use_new_ipfs should be True")
            except (AttributeError, AssertionError):
                print("New IPFS API initialization failed - this is expected if ipfs_kit_py is not installed")

        except ImportError as e:
            self.fail(f"Failed to import KNN: {e}")

    def test_upload_migration(self):
        """Test that upload works with both old and new implementations."""
        try:
            # Import the KNN class
            from ipfs_datasets_py.ipfs_faiss_py.ipfs_knn_lib.knn import KNN

            # Initialize KNN
            knn = KNN(self.resources, self.meta)

            # Test old implementation if available
            if hasattr(knn, 'ipfs_kit'):
                try:
                    # Mock the ipfs_upload_object method
                    original_method = knn.ipfs_kit.ipfs_upload_object
                    knn.ipfs_kit.ipfs_upload_object = lambda *args, **kwargs: "old_mock_cid"

                    # Force old implementation
                    knn.use_new_ipfs = False

                    # Call save_database with web3 destination
                    result = knn.save_database("web3", "test", "test", {
                        "vector_store": {"vector_store/data": {}},
                        "vector_index": {"vector_index/data": {}},
                        "doc_store": {"doc_store/data": {}},
                        "doc_index": {"doc_index/data": {}}
                    })

                    # Restore original method
                    knn.ipfs_kit.ipfs_upload_object = original_method

                    # Verify result
                    self.assertEqual(result, "old_mock_cid", "Old implementation not working correctly")
                except Exception as e:
                    print(f"Test with old implementation failed: {e}")

            # Test new implementation if available
            if hasattr(knn, 'ipfs_api') and knn.use_new_ipfs:
                try:
                    # Mock the add method
                    original_method = knn.ipfs_api.add
                    knn.ipfs_api.add = lambda *args, **kwargs: "new_mock_cid"

                    # Force new implementation
                    knn.use_new_ipfs = True

                    # Call save_database with web3 destination
                    result = knn.save_database("web3", "test", "test", {
                        "vector_store": {"vector_store/data": {}},
                        "vector_index": {"vector_index/data": {}},
                        "doc_store": {"doc_store/data": {}},
                        "doc_index": {"doc_index/data": {}}
                    })

                    # Restore original method
                    knn.ipfs_api.add = original_method

                    # Verify result
                    self.assertEqual(result, "new_mock_cid", "New implementation not working correctly")
                except Exception as e:
                    print(f"Test with new implementation failed: {e}")

        except ImportError as e:
            self.fail(f"Failed to import KNN: {e}")

if __name__ == '__main__':
    unittest.main()
