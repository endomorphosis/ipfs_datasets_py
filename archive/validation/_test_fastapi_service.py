#!/usr/bin/env python3
"""
FastAPI Service Testing Script

This script tests the FastAPI service endpoints to ensure they're working correctly.
"""

import asyncio
import aiohttp
import json
import logging
import time
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

class FastAPITester:
    """FastAPI service tester."""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = None
        self.token = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def test_health(self) -> bool:
        """Test health endpoint."""
        try:
            async with self.session.get(f"{self.base_url}/health") as response:
                data = await response.json()
                logger.info(f"✅ Health check: {data['status']}")
                return response.status == 200
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return False
    
    async def test_auth(self) -> bool:
        """Test authentication."""
        try:
            auth_data = {
                "username": "test_user",
                "password": "test_password"
            }
            
            async with self.session.post(
                f"{self.base_url}/auth/login",
                json=auth_data
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self.token = data.get("access_token")
                    logger.info("✅ Authentication successful")
                    return True
                else:
                    logger.error(f"❌ Authentication failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            return False
    
    async def test_tools_list(self) -> bool:
        """Test tools listing endpoint."""
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            async with self.session.get(
                f"{self.base_url}/tools/list",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    tool_count = data.get("count", 0)
                    logger.info(f"✅ Tools list: {tool_count} tools available")
                    return True
                else:
                    logger.error(f"❌ Tools list failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"❌ Tools list error: {e}")
            return False
    
    async def test_embedding_generation(self) -> bool:
        """Test embedding generation."""
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            embedding_data = {
                "text": "This is a test sentence for embedding generation.",
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "normalize": True,
                "batch_size": 1
            }
            
            async with self.session.post(
                f"{self.base_url}/embeddings/generate",
                json=embedding_data,
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Embedding generation successful")
                    return True
                else:
                    text = await response.text()
                    logger.error(f"❌ Embedding generation failed: {response.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Embedding generation error: {e}")
            return False
    
    async def test_dataset_operations(self) -> bool:
        """Test dataset operations."""
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            # Test dataset loading
            load_data = {
                "source": "test_dataset",
                "format": "json",
                "options": {}
            }
            
            async with self.session.post(
                f"{self.base_url}/datasets/load",
                json=load_data,
                headers=headers
            ) as response:
                if response.status == 200:
                    logger.info("✅ Dataset loading test successful")
                    return True
                else:
                    text = await response.text()
                    logger.warning(f"⚠️ Dataset loading test: {response.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Dataset operations error: {e}")
            return False
    
    async def test_admin_endpoints(self) -> bool:
        """Test admin endpoints."""
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            # Test system stats
            async with self.session.get(
                f"{self.base_url}/admin/stats",
                headers=headers
            ) as response:
                if response.status == 200:
                    logger.info("✅ Admin stats test successful")
                    return True
                else:
                    text = await response.text()
                    logger.warning(f"⚠️ Admin stats test: {response.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Admin endpoints error: {e}")
            return False
    
    async def run_all_tests(self) -> Dict[str, bool]:
        """Run all tests."""
        results = {}
        
        logger.info("🚀 Starting FastAPI service tests...")
        
        # Test health check first
        results["health"] = await self.test_health()
        if not results["health"]:
            logger.error("❌ Health check failed - service may not be running")
            return results
        
        # Test authentication
        results["auth"] = await self.test_auth()
        
        # Test other endpoints (even if auth fails, for testing purposes)
        results["tools_list"] = await self.test_tools_list()
        results["embedding_generation"] = await self.test_embedding_generation()
        results["dataset_operations"] = await self.test_dataset_operations()
        results["admin_endpoints"] = await self.test_admin_endpoints()
        
        return results

async def main():
    """Main test function."""
    logger.info("🧪 FastAPI Service Test Suite")
    logger.info("=" * 50)
    
    async with FastAPITester() as tester:
        results = await tester.run_all_tests()
    
    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("📊 Test Results Summary:")
    
    passed = 0
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.warning(f"⚠️ {total - passed} tests failed")
        return 1

if __name__ == "__main__":
    import sys
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
