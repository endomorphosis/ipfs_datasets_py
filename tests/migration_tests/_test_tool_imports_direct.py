# #!/usr/bin/env python3
# """
# Test specific tool imports step by step
# """
# import sys
# import os
# sys.path.insert(0, '.')

# print("Testing step-by-step tool imports...")

# # Test importing base_tool first
# print("\n=== Step 1: Import base_tool directly ===")
# try:
#     sys.path.insert(0, './ipfs_datasets_py/mcp_server/tools/development_tools/')
#     import base_tool
#     print("✅ base_tool module imported successfully")
#     BaseTool = base_tool.BaseTool
#     print("✅ BaseTool class accessed successfully")
# except Exception as e:
#     print(f"❌ base_tool import failed: {e}")
#     import traceback
#     traceback.print_exc()
#     sys.exit(1)

# # Test importing test_generator
# print("\n=== Step 2: Import test_generator directly ===")
# try:
#     import test_generator
#     print("✅ test_generator module imported successfully")
#     TestGenerator = test_generator.TestGenerator
#     print("✅ TestGenerator class accessed successfully")

#     # Try instantiating
#     test_gen = TestGenerator()
#     print("✅ TestGenerator instantiated successfully")
# except Exception as e:
#     print(f"❌ test_generator import/instantiation failed: {e}")
#     import traceback
#     traceback.print_exc()

# print("\n🎉 Step-by-step imports completed!")
