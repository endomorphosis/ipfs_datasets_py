#!/usr/bin/env python3
"""
Final integration test for the IPFS Embeddings migration.
Tests all major components and provides detailed reporting.
"""

import sys
import os
import anyio
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

class MigrationTester:
    """Comprehensive tester for the migration components."""
    
    def __init__(self):
        self.results = {}
        self.errors = []
        
    def test_module_imports(self) -> Dict[str, bool]:
        """Test importing all migrated modules."""
        tests = {}
        
        # Core embeddings modules
        try:
            from ipfs_datasets_py.embeddings.schema import (
                EmbeddingRequest, EmbeddingResponse, ChunkingStrategy
            )
            tests['embeddings_schema'] = True
        except Exception as e:
            tests['embeddings_schema'] = False
            self.errors.append(f"Embeddings schema: {e}")
            
        try:
            from ipfs_datasets_py.embeddings.chunker import (
                Chunker, ChunkingConfig
            )
            tests['embeddings_chunker'] = True
        except Exception as e:
            tests['embeddings_chunker'] = False
            self.errors.append(f"Embeddings chunker: {e}")
            
        try:
            from ipfs_datasets_py.embeddings.core import EmbeddingCore
            tests['embeddings_core'] = True
        except Exception as e:
            tests['embeddings_core'] = False
            self.errors.append(f"Embeddings core: {e}")
            
        # Vector stores
        try:
            from ipfs_datasets_py.vector_stores.base import BaseVectorStore
            tests['vector_store_base'] = True
        except Exception as e:
            tests['vector_store_base'] = False
            self.errors.append(f"Vector store base: {e}")
            
        try:
            from ipfs_datasets_py.vector_stores.qdrant_store import QdrantVectorStore
            tests['qdrant_store'] = True
        except Exception as e:
            tests['qdrant_store'] = False
            self.errors.append(f"Qdrant store: {e}")
            
        try:
            from ipfs_datasets_py.vector_stores.elasticsearch_store import ElasticsearchVectorStore
            tests['elasticsearch_store'] = True
        except Exception as e:
            tests['elasticsearch_store'] = False
            self.errors.append(f"Elasticsearch store: {e}")
            
        # MCP Tools
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation import generate_embedding
            tests['mcp_embedding_tools'] = True
        except Exception as e:
            tests['mcp_embedding_tools'] = False
            self.errors.append(f"MCP embedding tools: {e}")
            
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_search import semantic_search
            tests['mcp_search_tools'] = True
        except Exception as e:
            tests['mcp_search_tools'] = False
            self.errors.append(f"MCP search tools: {e}")
            
        return tests
    
    async def test_basic_functionality(self) -> Dict[str, bool]:
        """Test basic functionality of migrated components."""
        tests = {}
        
        # Test chunker
        try:
            from ipfs_datasets_py.embeddings.chunker import Chunker
            chunker = Chunker()
            test_text = "This is a test sentence. This is another test sentence. And one more for good measure."
            chunks = chunker.chunk_text(test_text, max_chunk_size=30)
            tests['chunker_functionality'] = len(chunks) > 1
        except Exception as e:
            tests['chunker_functionality'] = False
            self.errors.append(f"Chunker functionality: {e}")
            
        # Test schema creation
        try:
            from ipfs_datasets_py.embeddings.schema import EmbeddingRequest
            request = EmbeddingRequest(
                text="test text",
                model="test-model",
                parameters={}
            )
            tests['schema_functionality'] = request.text == "test text"
        except Exception as e:
            tests['schema_functionality'] = False
            self.errors.append(f"Schema functionality: {e}")
            
        # Test MCP embedding generation
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation import generate_embedding
            result = await generate_embedding(
                text="test text",
                model="mock-model"
            )
            tests['mcp_embedding_generation'] = result.get('status') == 'success'
        except Exception as e:
            tests['mcp_embedding_generation'] = False
            self.errors.append(f"MCP embedding generation: {e}")
            
        # Test MCP search
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_search import semantic_search
            result = await semantic_search(
                query="test query",
                collection="test-collection",
                top_k=5
            )
            tests['mcp_search'] = 'results' in result
        except Exception as e:
            tests['mcp_search'] = False
            self.errors.append(f"MCP search: {e}")
            
        return tests
    
    def test_package_exports(self) -> Dict[str, bool]:
        """Test that the main package exports work correctly."""
        tests = {}
        
        try:
            import ipfs_datasets_py
            tests['main_package_import'] = True
        except Exception as e:
            tests['main_package_import'] = False
            self.errors.append(f"Main package import: {e}")
            
        try:
            import ipfs_datasets_py
            has_embeddings = hasattr(ipfs_datasets_py, 'HAVE_EMBEDDINGS')
            tests['embeddings_flag'] = has_embeddings
        except Exception as e:
            tests['embeddings_flag'] = False
            self.errors.append(f"Embeddings flag: {e}")
            
        try:
            import ipfs_datasets_py
            has_vector_stores = hasattr(ipfs_datasets_py, 'HAVE_VECTOR_STORES')
            tests['vector_stores_flag'] = has_vector_stores
        except Exception as e:
            tests['vector_stores_flag'] = False
            self.errors.append(f"Vector stores flag: {e}")
            
        return tests
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all migration tests."""
        print("🧪 Running Migration Integration Tests")
        print("=" * 50)
        
        # Test module imports
        print("\n📦 Testing Module Imports...")
        import_results = self.test_module_imports()
        self._print_test_results(import_results, "Import")
        
        # Test basic functionality  
        print("\n⚙️  Testing Basic Functionality...")
        function_results = await self.test_basic_functionality()
        self._print_test_results(function_results, "Function")
        
        # Test package exports
        print("\n📤 Testing Package Exports...")
        export_results = self.test_package_exports()
        self._print_test_results(export_results, "Export")
        
        # Compile results
        all_results = {
            **import_results,
            **function_results,
            **export_results
        }
        
        return {
            'import_tests': import_results,
            'function_tests': function_results,
            'export_tests': export_results,
            'all_results': all_results,
            'errors': self.errors
        }
    
    def _print_test_results(self, results: Dict[str, bool], category: str):
        """Print test results in a formatted way."""
        for test_name, passed in results.items():
            status = "✅" if passed else "❌"
            print(f"  {status} {category} - {test_name}")
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate a detailed test report."""
        all_results = results['all_results']
        passed = sum(1 for result in all_results.values() if result)
        total = len(all_results)
        
        report = f"""
🧪 IPFS Embeddings Migration Test Report
========================================

Overall Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)

Import Tests: {sum(1 for r in results['import_tests'].values() if r)}/{len(results['import_tests'])} passed
Function Tests: {sum(1 for r in results['function_tests'].values() if r)}/{len(results['function_tests'])} passed  
Export Tests: {sum(1 for r in results['export_tests'].values() if r)}/{len(results['export_tests'])} passed

"""
        
        if results['errors']:
            report += "Errors Encountered:\n"
            for i, error in enumerate(results['errors'], 1):
                report += f"{i}. {error}\n"
        
        if passed == total:
            report += "\n🎉 All tests passed! The migration is successful.\n"
        else:
            report += f"\n⚠️  {total - passed} tests failed. Review errors above.\n"
            
        return report

async def main():
    """Main test execution function."""
    tester = MigrationTester()
    results = await tester.run_all_tests()
    
    print("\n" + "=" * 50)
    print(tester.generate_report(results))
    
    # Return appropriate exit code
    all_results = results['all_results']
    passed = sum(1 for result in all_results.values() if result)
    total = len(all_results)
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)
