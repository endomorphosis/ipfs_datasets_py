"""
Test the Test Generator Tool

Basic validation that the test generator tool works correctly.
"""

import anyio
import json
import tempfile
from pathlib import Path
import sys

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator


async def test_basic_test_generation():
    """Test basic test generation functionality."""

    # Sample test specification
    test_spec = {
        "imports": [
            "import unittest",
            "from pathlib import Path"
        ],
        "fixtures": [
            {
                "name": "sample_data",
                "value": "{'name': 'test', 'value': 42}",
                "description": "Sample test data"
            }
        ],
        "tests": [
            {
                "name": "sample_test",
                "description": "Test sample functionality",
                "assertions": [
                    "self.assertEqual(self.sample_data['name'], 'test')",
                    "self.assertEqual(self.sample_data['value'], 42)"
                ],
                "parametrized": False
            },
            {
                "name": "dataset_load_test",
                "description": "Test dataset loading functionality",
                "assertions": [
                    "self.assertIsNotNone(self.sample_dataset)",
                    "self.assertEqual(len(self.sample_dataset), 2)"
                ],
                "parametrized": False
            }
        ]
    }

    # Create temporary output directory
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Testing test generation in: {temp_dir}")

        # Test unittest generation (synchronous call)
        result = test_generator(
            name="sample_unittest_test",
            description="A sample test generated for validation",
            test_specification=test_spec,
            output_dir=temp_dir,
            harness="unittest"
        )

        print("Unittest generation result:")
        print(json.dumps(result, indent=2))

        # Verify the file was created
        if result.get('success'):
            test_file = Path(result['result']['test_file'])
            if test_file.exists():
                print(f"\n✅ Test file created: {test_file}")
                print(f"File size: {test_file.stat().st_size} bytes")

                # Show first few lines
                with open(test_file, 'r') as f:
                    lines = f.readlines()[:20]
                    print("\nFirst 20 lines of generated test:")
                    print("=" * 50)
                    for i, line in enumerate(lines, 1):
                        print(f"{i:2d}: {line.rstrip()}")
                    print("=" * 50)
            else:
                print(f"❌ Test file not found: {test_file}")
        else:
            print(f"❌ Test generation failed: {result}")

        # Test pytest generation
        print("\n" + "="*60)
        print("Testing pytest generation...")

        result_pytest = test_generator(
            name="sample_pytest_test",
            description="A sample pytest test generated for validation",
            test_specification=test_spec,
            output_dir=temp_dir,
            harness="pytest"
        )

        print("Pytest generation result:")
        print(json.dumps(result_pytest, indent=2))

        if result_pytest.get('success'):
            test_file = Path(result_pytest['result']['test_file'])
            if test_file.exists():
                print(f"\n✅ Pytest file created: {test_file}")
                print(f"File size: {test_file.stat().st_size} bytes")

                # Show first few lines
                with open(test_file, 'r') as f:
                    lines = f.readlines()[:20]
                    print("\nFirst 20 lines of generated pytest:")
                    print("=" * 50)
                    for i, line in enumerate(lines, 1):
                        print(f"{i:2d}: {line.rstrip()}")
                    print("=" * 50)


async def test_json_string_specification():
    """Test test generation with JSON string specification."""

    test_spec_json = json.dumps({
        "tests": [
            {
                "name": "json_test",
                "description": "Test from JSON string specification",
                "assertions": ["self.assertTrue(True)"],
                "parametrized": False
            }
        ]
    })

    with tempfile.TemporaryDirectory() as temp_dir:
        result = test_generator(
            name="json_string_test",
            description="Test with JSON string input",
            test_specification=test_spec_json,
            output_dir=temp_dir
        )

        print("\nJSON string test generation result:")
        print(json.dumps(result, indent=2))

        if result.get('success'):
            print("✅ JSON string specification test passed")
        else:
            print("❌ JSON string specification test failed")


async def main():
    """Run all tests."""
    print("Testing IPFS Datasets Test Generator Tool")
    print("=" * 60)

    try:
        await test_basic_test_generation()
        await test_json_string_specification()
        print("\n🎉 All tests completed!")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    anyio.run(main())
