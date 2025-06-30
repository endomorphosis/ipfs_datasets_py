#!/usr/bin/env python3
"""
Phase 5: Final Validation & Deployment Script

This script performs comprehensive validation and prepares for production deployment.
"""

import sys
import logging
import asyncio
import time
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any
import requests
import threading

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class Phase5Validator:
    """Comprehensive Phase 5 validation and deployment preparation."""
    
    def __init__(self):
        self.results = {}
        self.fastapi_process = None
        self.test_port = 8001
        
    def validate_core_imports(self) -> bool:
        """Validate all core module imports."""
        logger.info("🔍 Validating core module imports...")
        
        try:
            # Core ipfs_datasets_py modules
            import ipfs_datasets_py
            from ipfs_datasets_py import embeddings, vector_stores
            from ipfs_datasets_py.mcp_server.server import server
            from ipfs_datasets_py.fastapi_service import app, settings
            from ipfs_datasets_py.fastapi_config import Settings
            
            logger.info("✅ All core modules imported successfully")
            self.results['core_imports'] = True
            return True
            
        except Exception as e:
            logger.error(f"❌ Core import error: {e}")
            self.results['core_imports'] = False
            return False
    
    def validate_mcp_tools(self) -> bool:
        """Validate MCP tool registration and functionality."""
        logger.info("🔍 Validating MCP tools...")
        
        try:
            from ipfs_datasets_py.mcp_server.server import server
            
            # Check tool registration
            tools = server.list_tools()
            tool_count = len(tools.tools) if hasattr(tools, 'tools') else 0
            
            logger.info(f"✅ MCP Server registered {tool_count} tools")
            
            # Validate key tool categories
            expected_categories = [
                'dataset_tools', 'ipfs_tools', 'embedding_tools', 'vector_tools',
                'audit_tools', 'admin_tools', 'cache_tools', 'monitoring_tools'
            ]
            
            validated_categories = 0
            for category in expected_categories:
                try:
                    module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
                    __import__(module_path)
                    validated_categories += 1
                except ImportError:
                    logger.warning(f"⚠️ Category {category} not found")
            
            logger.info(f"✅ Validated {validated_categories}/{len(expected_categories)} tool categories")
            
            self.results['mcp_tools'] = {
                'total_tools': tool_count,
                'validated_categories': validated_categories,
                'success': validated_categories >= 6  # At least 6 core categories
            }
            
            return validated_categories >= 6
            
        except Exception as e:
            logger.error(f"❌ MCP tools validation error: {e}")
            self.results['mcp_tools'] = {'success': False, 'error': str(e)}
            return False
    
    def validate_embeddings_vectorstores(self) -> bool:
        """Validate embeddings and vector store functionality."""
        logger.info("🔍 Validating embeddings and vector stores...")
        
        try:
            from ipfs_datasets_py.embeddings.core import EmbeddingManager
            from ipfs_datasets_py.vector_stores.base import BaseVectorStore
            from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
            
            # Test embedding manager
            embedding_manager = EmbeddingManager()
            logger.info("✅ EmbeddingManager instantiated")
            
            # Test vector store
            faiss_store = FAISSVectorStore(dimension=384)
            logger.info("✅ FAISSVectorStore instantiated")
            
            self.results['embeddings_vectorstores'] = True
            return True
            
        except Exception as e:
            logger.error(f"❌ Embeddings/VectorStores validation error: {e}")
            self.results['embeddings_vectorstores'] = False
            return False
    
    def start_fastapi_service(self) -> bool:
        """Start FastAPI service for testing."""
        logger.info("🚀 Starting FastAPI service for testing...")
        
        try:
            import subprocess
            import time
            
            # Start FastAPI service
            cmd = [
                str(project_root / ".venv" / "bin" / "python"),
                str(project_root / "start_fastapi.py"),
                "--port", str(self.test_port),
                "--host", "127.0.0.1"
            ]
            
            self.fastapi_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(project_root)
            )
            
            # Wait for service to start
            time.sleep(5)
            
            # Test health endpoint
            response = requests.get(f"http://127.0.0.1:{self.test_port}/health", timeout=10)
            if response.status_code == 200:
                logger.info("✅ FastAPI service started and health check passed")
                return True
            else:
                logger.error(f"❌ Health check failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ FastAPI service start error: {e}")
            return False
    
    def validate_api_endpoints(self) -> bool:
        """Validate key API endpoints."""
        logger.info("🔍 Validating API endpoints...")
        
        base_url = f"http://127.0.0.1:{self.test_port}"
        
        endpoints_to_test = [
            "/health",
            "/api/v1/auth/status",
            "/api/v1/embeddings/models",
            "/api/v1/datasets/list",
            "/api/v1/ipfs/status"
        ]
        
        passed = 0
        total = len(endpoints_to_test)
        
        for endpoint in endpoints_to_test:
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=5)
                if response.status_code in [200, 401]:  # 401 is OK for auth endpoints
                    passed += 1
                    logger.info(f"✅ {endpoint} - Status: {response.status_code}")
                else:
                    logger.warning(f"⚠️ {endpoint} - Status: {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ {endpoint} - Error: {e}")
        
        success = passed >= (total * 0.6)  # At least 60% should pass
        self.results['api_endpoints'] = {
            'passed': passed,
            'total': total,
            'success': success
        }
        
        logger.info(f"✅ API validation: {passed}/{total} endpoints passed")
        return success
    
    def stop_fastapi_service(self):
        """Stop the FastAPI service."""
        if self.fastapi_process:
            logger.info("🛑 Stopping FastAPI service...")
            self.fastapi_process.terminate()
            self.fastapi_process.wait(timeout=10)
            self.fastapi_process = None
    
    def validate_production_readiness(self) -> bool:
        """Validate production readiness checklist."""
        logger.info("🔍 Validating production readiness...")
        
        checks = {}
        
        # Check required files exist
        required_files = [
            "requirements.txt",
            "pyproject.toml",
            "Dockerfile",
            "DEPLOYMENT_GUIDE.md",
            ".env.example" if Path(".env.example").exists() else None
        ]
        
        file_checks = []
        for file in required_files:
            if file and Path(file).exists():
                file_checks.append(True)
                logger.info(f"✅ {file} exists")
            elif file:
                file_checks.append(False)
                logger.warning(f"⚠️ {file} missing")
        
        checks['required_files'] = all(file_checks)
        
        # Check configuration
        try:
            from ipfs_datasets_py.fastapi_config import Settings
            settings = Settings()
            checks['configuration'] = True
            logger.info("✅ Configuration validated")
        except Exception as e:
            checks['configuration'] = False
            logger.error(f"❌ Configuration error: {e}")
        
        # Check dependencies
        try:
            result = subprocess.run([
                str(project_root / ".venv" / "bin" / "pip"),
                "check"
            ], capture_output=True, text=True)
            checks['dependencies'] = result.returncode == 0
            if result.returncode == 0:
                logger.info("✅ Dependencies validated")
            else:
                logger.warning(f"⚠️ Dependency issues: {result.stdout}")
        except Exception as e:
            checks['dependencies'] = False
            logger.error(f"❌ Dependency check error: {e}")
        
        success = all(checks.values())
        self.results['production_readiness'] = checks
        
        return success
    
    def run_load_test(self) -> bool:
        """Run basic load test on FastAPI service."""
        logger.info("🔍 Running basic load test...")
        
        try:
            import concurrent.futures
            import time
            
            def make_request():
                try:
                    response = requests.get(f"http://127.0.0.1:{self.test_port}/health", timeout=5)
                    return response.status_code == 200
                except:
                    return False
            
            # Run 20 concurrent requests
            start_time = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(make_request) for _ in range(20)]
                results = [future.result() for future in concurrent.futures.as_completed(futures)]
            
            end_time = time.time()
            duration = end_time - start_time
            success_count = sum(results)
            success_rate = success_count / len(results)
            
            logger.info(f"✅ Load test: {success_count}/20 requests successful in {duration:.2f}s")
            logger.info(f"✅ Success rate: {success_rate:.1%}")
            
            self.results['load_test'] = {
                'success_count': success_count,
                'total_requests': 20,
                'success_rate': success_rate,
                'duration': duration,
                'success': success_rate >= 0.8  # At least 80% success rate
            }
            
            return success_rate >= 0.8
            
        except Exception as e:
            logger.error(f"❌ Load test error: {e}")
            self.results['load_test'] = {'success': False, 'error': str(e)}
            return False
    
    def generate_deployment_report(self):
        """Generate comprehensive deployment report."""
        logger.info("📋 Generating deployment report...")
        
        report = {
            "phase": "Phase 5: Final Validation & Deployment",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "validation_results": self.results,
            "overall_status": "READY" if self.is_deployment_ready() else "NOT READY",
            "recommendations": self.get_recommendations()
        }
        
        # Save report
        report_path = project_root / "PHASE5_VALIDATION_REPORT.md"
        with open(report_path, 'w') as f:
            f.write("# Phase 5: Final Validation & Deployment Report\n\n")
            f.write(f"**Generated:** {report['timestamp']}\n")
            f.write(f"**Status:** {report['overall_status']}\n\n")
            
            f.write("## Validation Results\n\n")
            for test_name, result in self.results.items():
                status = "✅ PASS" if result.get('success', result) else "❌ FAIL"
                f.write(f"- **{test_name.replace('_', ' ').title()}:** {status}\n")
                
                if isinstance(result, dict) and 'error' in result:
                    f.write(f"  - Error: {result['error']}\n")
                elif isinstance(result, dict):
                    for key, value in result.items():
                        if key != 'success':
                            f.write(f"  - {key}: {value}\n")
            
            f.write("\n## Recommendations\n\n")
            for rec in report['recommendations']:
                f.write(f"- {rec}\n")
            
            f.write(f"\n## Full Report JSON\n\n```json\n{json.dumps(report, indent=2)}\n```\n")
        
        logger.info(f"📋 Report saved to {report_path}")
        return report
    
    def is_deployment_ready(self) -> bool:
        """Check if system is ready for deployment."""
        required_tests = [
            'core_imports',
            'mcp_tools',
            'embeddings_vectorstores',
            'production_readiness'
        ]
        
        for test in required_tests:
            result = self.results.get(test)
            if not (result.get('success', result) if isinstance(result, dict) else result):
                return False
        
        return True
    
    def get_recommendations(self) -> List[str]:
        """Get deployment recommendations based on validation results."""
        recommendations = []
        
        if not self.results.get('core_imports'):
            recommendations.append("Fix core module imports before deployment")
        
        if not self.results.get('mcp_tools', {}).get('success'):
            recommendations.append("Ensure all MCP tools are properly registered")
        
        if not self.results.get('production_readiness', {}).get('dependencies'):
            recommendations.append("Run 'pip check' to resolve dependency conflicts")
        
        if self.results.get('load_test', {}).get('success_rate', 1) < 0.9:
            recommendations.append("Consider performance optimization for production load")
        
        if not recommendations:
            recommendations.append("System is ready for production deployment!")
            recommendations.append("Follow DEPLOYMENT_GUIDE.md for deployment instructions")
            recommendations.append("Consider setting up monitoring and logging")
            recommendations.append("Set up CI/CD pipeline for automated deployments")
        
        return recommendations
    
    async def run_full_validation(self):
        """Run complete Phase 5 validation."""
        logger.info("🚀 Starting Phase 5: Final Validation & Deployment")
        logger.info("=" * 60)
        
        try:
            # Core validation
            await asyncio.get_event_loop().run_in_executor(None, self.validate_core_imports)
            await asyncio.get_event_loop().run_in_executor(None, self.validate_mcp_tools)
            await asyncio.get_event_loop().run_in_executor(None, self.validate_embeddings_vectorstores)
            await asyncio.get_event_loop().run_in_executor(None, self.validate_production_readiness)
            
            # FastAPI validation
            if await asyncio.get_event_loop().run_in_executor(None, self.start_fastapi_service):
                await asyncio.get_event_loop().run_in_executor(None, self.validate_api_endpoints)
                await asyncio.get_event_loop().run_in_executor(None, self.run_load_test)
                self.stop_fastapi_service()
            
            # Generate report
            report = self.generate_deployment_report()
            
            logger.info("=" * 60)
            logger.info(f"🎯 Phase 5 Validation Complete: {report['overall_status']}")
            
            if self.is_deployment_ready():
                logger.info("🎉 System is READY for production deployment!")
                logger.info("📖 See DEPLOYMENT_GUIDE.md for deployment instructions")
            else:
                logger.warning("⚠️ System requires fixes before deployment")
                logger.info("📋 Check PHASE5_VALIDATION_REPORT.md for details")
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Validation error: {e}")
            self.stop_fastapi_service()
            raise

def main():
    """Main validation function."""
    validator = Phase5Validator()
    
    try:
        loop = asyncio.get_event_loop()
        report = loop.run_until_complete(validator.run_full_validation())
        
        # Exit with appropriate code
        exit_code = 0 if validator.is_deployment_ready() else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        logger.info("🛑 Validation interrupted by user")
        validator.stop_fastapi_service()
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        validator.stop_fastapi_service()
        sys.exit(1)

if __name__ == "__main__":
    main()
