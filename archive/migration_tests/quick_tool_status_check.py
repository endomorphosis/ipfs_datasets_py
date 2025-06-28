#!/usr/bin/env python3

import asyncio
import sys
import json
import time
from datetime import datetime
import traceback
import tempfile
import os
from pathlib import Path

async def test_critical_tools():
    """Test the most critical tools to identify what still needs fixing"""
    
    results = {}
    
    # Test IPFS tools (critical for storage)
    print("=== Testing IPFS Tools ===")
    try:
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs
        
        # Test pin_to_ipfs
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write('Test content for IPFS')
            test_file = f.name
        
        try:
            pin_result = await pin_to_ipfs(test_file)
            results['pin_to_ipfs'] = {'status': 'success', 'result': pin_result}
            print(f"✓ pin_to_ipfs: SUCCESS")
        except Exception as e:
            results['pin_to_ipfs'] = {'status': 'error', 'error': str(e)}
            print(f"✗ pin_to_ipfs: FAILED - {e}")
        finally:
            os.unlink(test_file)
        
        # Test get_from_ipfs
        try:
            get_result = await get_from_ipfs("QmTestCID123")
            results['get_from_ipfs'] = {'status': 'success', 'result': get_result}
            print(f"✓ get_from_ipfs: SUCCESS")
        except Exception as e:
            results['get_from_ipfs'] = {'status': 'error', 'error': str(e)}
            print(f"✗ get_from_ipfs: FAILED - {e}")
            
    except Exception as e:
        print(f"✗ Failed to import IPFS tools: {e}")
    
    # Test Dataset tools (critical for data handling)
    print("\n=== Testing Dataset Tools ===")
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
        
        # Test load_dataset with a simple dataset
        try:
            load_result = await load_dataset("wikipedia", format="json", options={"split": "train[:5]"})
            results['load_dataset'] = {'status': 'success', 'summary': 'Loaded dataset successfully'}
            print(f"✓ load_dataset: SUCCESS")
        except Exception as e:
            results['load_dataset'] = {'status': 'error', 'error': str(e)}
            print(f"✗ load_dataset: FAILED - {e}")
        
        # Test save_dataset
        try:
            test_data = {"data": [{"text": "test", "label": 1}]}
            with tempfile.TemporaryDirectory() as tmpdir:
                save_result = await save_dataset(test_data, f"{tmpdir}/test.json")
                results['save_dataset'] = {'status': 'success', 'summary': 'Saved dataset successfully'}
                print(f"✓ save_dataset: SUCCESS")
        except Exception as e:
            results['save_dataset'] = {'status': 'error', 'error': str(e)}
            print(f"✗ save_dataset: FAILED - {e}")
        
        # Test process_dataset
        try:
            test_data = {"data": [{"text": "hello", "score": 5}, {"text": "world", "score": 3}]}
            operations = [{"type": "filter", "condition": "score > 4"}]
            process_result = await process_dataset(test_data, operations)
            results['process_dataset'] = {'status': 'success', 'summary': 'Processed dataset successfully'}
            print(f"✓ process_dataset: SUCCESS")
        except Exception as e:
            results['process_dataset'] = {'status': 'error', 'error': str(e)}
            print(f"✗ process_dataset: FAILED - {e}")
            
    except Exception as e:
        print(f"✗ Failed to import dataset tools: {e}")
    
    # Test Vector tools (critical for search)
    print("\n=== Testing Vector Tools ===")
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
        
        # Test create_vector_index
        try:
            vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
            metadata = [{"id": i} for i in range(3)]
            create_result = await create_vector_index(vectors, metadata=metadata)
            results['create_vector_index'] = {'status': 'success', 'summary': 'Created vector index successfully'}
            print(f"✓ create_vector_index: SUCCESS")
            
            # Test search_vector_index using the created index
            if create_result.get('status') == 'success':
                index_id = create_result.get('index_id')
                search_result = await search_vector_index(index_id, [0.1, 0.2, 0.3], top_k=2)
                results['search_vector_index'] = {'status': 'success', 'summary': 'Searched vector index successfully'}
                print(f"✓ search_vector_index: SUCCESS")
            else:
                raise Exception("Index creation failed")
                
        except Exception as e:
            results['create_vector_index'] = {'status': 'error', 'error': str(e)}
            results['search_vector_index'] = {'status': 'error', 'error': f"Dependent on create_vector_index: {e}"}
            print(f"✗ create_vector_index: FAILED - {e}")
            print(f"✗ search_vector_index: FAILED - dependent failure")
            
    except Exception as e:
        print(f"✗ Failed to import vector tools: {e}")
    
    # Test Audit tools (important for compliance)
    print("\n=== Testing Audit Tools ===")
    try:
        from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report
        
        # Test record_audit_event
        try:
            event_result = await record_audit_event("test.action", resource_id="test_resource")
            results['record_audit_event'] = {'status': 'success', 'summary': 'Recorded audit event successfully'}
            print(f"✓ record_audit_event: SUCCESS")
        except Exception as e:
            results['record_audit_event'] = {'status': 'error', 'error': str(e)}
            print(f"✗ record_audit_event: FAILED - {e}")
        
        # Test generate_audit_report
        try:
            report_result = await generate_audit_report("comprehensive")
            results['generate_audit_report'] = {'status': 'success', 'summary': 'Generated audit report successfully'}
            print(f"✓ generate_audit_report: SUCCESS")
        except Exception as e:
            results['generate_audit_report'] = {'status': 'error', 'error': str(e)}
            print(f"✗ generate_audit_report: FAILED - {e}")
            
    except Exception as e:
        print(f"✗ Failed to import audit tools: {e}")
    
    # Test Web Archive tools (check if they're all failing)
    print("\n=== Testing Web Archive Tools ===")
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_webpage import archive_webpage
        
        try:
            archive_result = await archive_webpage("https://example.com", format="mhtml")
            results['archive_webpage'] = {'status': 'success', 'summary': 'Archived webpage successfully'}
            print(f"✓ archive_webpage: SUCCESS")
        except Exception as e:
            results['archive_webpage'] = {'status': 'error', 'error': str(e)}
            print(f"✗ archive_webpage: FAILED - {e}")
            
    except Exception as e:
        print(f"✗ Failed to import web archive tools: {e}")
    
    # Summary
    print("\n=== SUMMARY ===")
    success_count = sum(1 for r in results.values() if r.get('status') == 'success')
    total_count = len(results)
    print(f"Tools tested: {total_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_count - success_count}")
    print(f"Success rate: {success_count/total_count*100:.1f}%")
    
    # Save results
    with open('/home/barberb/ipfs_datasets_py/critical_tools_status.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total': total_count,
                'successful': success_count,
                'failed': total_count - success_count,
                'success_rate': success_count/total_count*100
            },
            'results': results
        }, f, indent=2)
    
    return results

if __name__ == "__main__":
    asyncio.run(test_critical_tools())
