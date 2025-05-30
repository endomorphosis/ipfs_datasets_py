import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import datetime

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockProvenanceManager:
    def record_provenance(self, entity_id, entity_type, activity_type, agent_id, metadata):
        if entity_id == "dataset_123" and entity_type == "dataset" and activity_type == "creation" and agent_id == "user_abc":
            return {"provenance_id": "prov_001", "timestamp": datetime.datetime.now().isoformat()}
        raise Exception("Failed to record provenance in mock manager")

class TestMCPRecordProvenance(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_provenance_manager = MockProvenanceManager()
        self.patcher = patch('ipfs_datasets_py.data_provenance.provenance_manager.ProvenanceManager', return_value=self.mock_provenance_manager)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_record_provenance_success(self):
        from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance

        entity_id = "dataset_123"
        entity_type = "dataset"
        activity_type = "creation"
        agent_id = "user_abc"
        metadata = {"source": "web_scrape", "version": "1.0"}

        result = await record_provenance(
            entity_id=entity_id,
            entity_type=entity_type,
            activity_type=activity_type,
            agent_id=agent_id,
            metadata=metadata
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["entity_id"], entity_id)
        self.assertEqual(result["provenance_id"], "prov_001")
        self.assertIsNotNone(result["timestamp"])

    async def test_record_provenance_failure(self):
        from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance

        entity_id = "error_dataset"
        entity_type = "dataset"
        activity_type = "creation"
        agent_id = "user_abc"
        metadata = {"source": "web_scrape", "version": "1.0"}
        self.mock_provenance_manager.record_provenance = MagicMock(side_effect=Exception("Provenance recording failed"))

        result = await record_provenance(
            entity_id=entity_id,
            entity_type=entity_type,
            activity_type=activity_type,
            agent_id=agent_id,
            metadata=metadata
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("Provenance recording failed", result["message"])
        self.assertEqual(result["entity_id"], entity_id)

if __name__ == '__main__':
    unittest.main()
