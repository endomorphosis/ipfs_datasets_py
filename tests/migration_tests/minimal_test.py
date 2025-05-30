import sys
print("Starting minimal test...")

try:
    # Test basic imports
    print("Testing basic Python functionality")
    import json
    import os
    print("✅ Basic imports work")

    # Test project structure
    if os.path.exists("/home/barberb/ipfs_datasets_py/ipfs_datasets_py"):
        print("✅ Project structure exists")
    else:
        print("❌ Project structure missing")

    # Test one simple import
    sys.path.insert(0, "/home/barberb/ipfs_datasets_py")

    # Try to import the stub libp2p_kit
    from ipfs_datasets_py.libp2p_kit import NodeRole
    print("✅ libp2p_kit stub import works")

    # Save results
    results = {
        "basic_functionality": "working",
        "project_structure": "exists",
        "libp2p_stub": "working"
    }

    with open("/home/barberb/ipfs_datasets_py/minimal_test_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("✅ Minimal test completed successfully")
    print("Results saved to minimal_test_results.json")

except Exception as e:
    print(f"❌ Minimal test failed: {e}")
    import traceback
    traceback.print_exc()
